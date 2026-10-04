"""API endpoints for dive code parsing, validation, and reference"""

from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.write_guard import require_owner_for_mutation
from app.schemas.dive_code import (
    DiveCodeInput,
    DiveCodeParsed,
    DiveCodeValidation,
    DiveCodeReference,
    ValidationError,
    DiveCodeBatch,
    DiveCodeBatchResponse,
)
from app.services.dive_code_parser import DiveCodeParser
from app.services.dive_code_validator import DiveCodeValidator
from app.services.workspace_access import require_workspace_read
from app.models import FINADiveCode

router = APIRouter(prefix="/dive-codes", tags=["dive-codes"], dependencies=[Depends(require_owner_for_mutation), Depends(require_workspace_read)])


@router.post("/parse", response_model=DiveCodeParsed)
async def parse_dive_code(request: DiveCodeInput) -> DiveCodeParsed:
    """
    Parse a dive code from app caption format or FINA format.

    App format: DIVECODE PERF [HEIGHT] [FLAGS]
    Example: "101B M 3m SYNC"
    Example: "5231D G 10m"
    Example: "101B" (minimal)

    Returns parsed dive code with all components.
    """
    result = DiveCodeParser.parse(request.raw_input)

    if not result.is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse dive code: {result.error}",
        )

    return DiveCodeParsed(
        dive_code=result.dive_code,
        group=result.group,
        direction=result.direction,
        position=result.position,
        performance=result.performance,
        performance_numeric=result.performance_numeric,
        height=result.height,
        platform_type=result.platform_type,
        is_sync=result.is_sync,
        is_smack=result.is_smack,
        is_valid=result.is_valid,
    )


@router.post("/validate", response_model=DiveCodeValidation)
async def validate_dive_code(
    request: DiveCodeInput, db: Session = Depends(get_db)
) -> DiveCodeValidation:
    """
    Validate a dive code against FINA rules.

    Returns validation result with errors, warnings, and suggestions.
    """
    validator = DiveCodeValidator(db)

    # Parse first
    parsed = DiveCodeParser.parse(request.raw_input)
    if not parsed.is_valid:
        return DiveCodeValidation(
            dive_code=request.raw_input,
            is_valid=False,
            errors=[
                ValidationError(
                    field="dive_code",
                    message=parsed.error or "Invalid dive code",
                    severity="error",
                )
            ],
            is_official_fina=False,
        )

    # Validate
    is_valid, errors = validator.validate_parsed_code(parsed)
    is_official = validator.check_if_official_fina_dive(parsed.dive_code)

    error_list = [
        ValidationError(field="dive_code", message=error, severity="error")
        for error in errors
    ]

    suggestions = validator.get_suggestions(parsed.dive_code) if errors else None

    return DiveCodeValidation(
        dive_code=parsed.dive_code,
        is_valid=is_valid,
        errors=error_list,
        is_official_fina=is_official,
        suggestions=suggestions,
    )


@router.get("/reference", response_model=List[DiveCodeReference])
async def get_all_reference_dives(
    db: Session = Depends(get_db),
    group: int = None,
    is_twisting: bool = None,
) -> List[DiveCodeReference]:
    """
    Get all FINA dive codes with optional filtering.

    Query parameters:
    - group: Filter by group (1-6)
    - is_twisting: Filter by twisting status
    """
    query = db.query(FINADiveCode)

    if group is not None:
        query = query.filter_by(group=group)

    if is_twisting is not None:
        query = query.filter_by(is_twisting=int(is_twisting))

    dives = query.all()

    return [
        DiveCodeReference(
            dive_code=dive.dive_code,
            group=dive.group,
            group_name=dive.group_name,
            direction=dive.direction,
            position=dive.position,
            position_name=dive.position_name,
            rotations=dive.rotations,
            twists=dive.twists,
            official_name=dive.official_name,
            description=dive.description,
            is_twisting=bool(dive.is_twisting),
            is_flying=bool(dive.is_flying),
            is_armstand=bool(dive.is_armstand),
        )
        for dive in dives
    ]


@router.get("/{dive_code}", response_model=DiveCodeReference)
async def get_dive_code(dive_code: str, db: Session = Depends(get_db)) -> DiveCodeReference:
    """
    Get details for a specific FINA dive code.

    Example: GET /api/v1/dive-codes/101B
    """
    dive_code = dive_code.strip().upper()
    dive = db.query(FINADiveCode).filter_by(dive_code=dive_code).first()

    if not dive:
        raise HTTPException(
            status_code=404,
            detail=f"Dive code '{dive_code}' not found in FINA database",
        )

    return DiveCodeReference(
        dive_code=dive.dive_code,
        group=dive.group,
        group_name=dive.group_name,
        direction=dive.direction,
        position=dive.position,
        position_name=dive.position_name,
        rotations=dive.rotations,
        twists=dive.twists,
        official_name=dive.official_name,
        description=dive.description,
        is_twisting=bool(dive.is_twisting),
        is_flying=bool(dive.is_flying),
        is_armstand=bool(dive.is_armstand),
    )


@router.get("/official-only/all", response_model=List[DiveCodeReference])
async def get_official_dives_only(
    db: Session = Depends(get_db),
) -> List[DiveCodeReference]:
    """
    Get only official FINA dives (all dives in the database).

    This is useful for UI dropdowns and reference lists.
    """
    dives = db.query(FINADiveCode).order_by(FINADiveCode.dive_code).all()

    return [
        DiveCodeReference(
            dive_code=dive.dive_code,
            group=dive.group,
            group_name=dive.group_name,
            direction=dive.direction,
            position=dive.position,
            position_name=dive.position_name,
            rotations=dive.rotations,
            twists=dive.twists,
            official_name=dive.official_name,
            description=dive.description,
            is_twisting=bool(dive.is_twisting),
            is_flying=bool(dive.is_flying),
            is_armstand=bool(dive.is_armstand),
        )
        for dive in dives
    ]


@router.post("/batch-parse", response_model=DiveCodeBatchResponse)
async def batch_parse_dive_codes(request: DiveCodeBatch) -> DiveCodeBatchResponse:
    """
    Parse multiple dive codes in one request.

    Useful for bulk imports or batch validation.
    """
    total = len(request.codes)
    successful = 0
    failed = 0
    results = []

    for code in request.codes:
        parsed = DiveCodeParser.parse(code)

        if parsed.is_valid:
            successful += 1
            results.append({
                "input": code,
                "status": "success",
                "dive_code": parsed.dive_code,
                "group": parsed.group,
                "direction": parsed.direction,
                "position": parsed.position,
                "height": parsed.height,
            })
        else:
            failed += 1
            results.append({
                "input": code,
                "status": "failed",
                "error": parsed.error,
            })

    return DiveCodeBatchResponse(
        total=total,
        successful=successful,
        failed=failed,
        results=results,
    )
