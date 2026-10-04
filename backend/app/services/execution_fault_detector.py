"""Execution Fault Detector service - analyzes dive execution and detects faults"""

from typing import Optional, Dict, List, Tuple
from decimal import Decimal
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.execution_fault import ExecutionFault
from app.models.fina_dive_code import FINADiveCode
from app.services.performance_scoring import athlete_score_10, dive_score_10


@dataclass
class ExecutionMetrics:
    """Metrics for dive execution analysis"""
    phase: int  # 1 or 2
    rotation_degrees: float  # 0-1440 for full rotations
    entry_distance_from_center: float  # Distance in cm from center line
    entry_angle_degrees: float  # 0-90, where 0 is vertical
    height_achieved: float  # Estimated height in cm
    spin_consistency: float  # 0.0-1.0, how consistent the spin was
    overall_score: float  # 0.0-10.0


class ExecutionFaultDetector:
    """Detects and analyzes execution faults in dives"""

    # Fault codes and their definitions
    FAULT_CODES = {
        "UR": {"name": "Under-Rotation", "severity_weight": 1.5},
        "OR": {"name": "Over-Rotation", "severity_weight": 1.2},
        "LE": {"name": "Late Entry", "severity_weight": 1.0},
        "EE": {"name": "Early Entry", "severity_weight": 0.8},
        "LS": {"name": "Lack of Spin/Twist", "severity_weight": 1.0},
        "LH": {"name": "Lack of Height", "severity_weight": 0.9},
        "PH": {"name": "Pike/Twist Issue", "severity_weight": 0.7},
        "SA": {"name": "Starting Approach Issue", "severity_weight": 0.8},
        "LK": {"name": "Lack of Control", "severity_weight": 1.1},
        "SK": {"name": "Splash/Kiss", "severity_weight": 0.6},
    }

    # Severity thresholds (points deducted)
    SEVERITY_MAPPING = {
        "HIGH": {"points_deducted": 1.5, "min_threshold": 1.5},
        "MEDIUM": {"points_deducted": 0.75, "max_threshold": 1.4, "min_threshold": 0.75},
        "LOW": {"points_deducted": 0.25, "max_threshold": 0.74},
    }

    # Fault thresholds for detection
    FAULT_THRESHOLDS = {
        "UR": {"min_degrees": 30, "max_degrees": 900},  # Under-rotated: less than target
        "OR": {"min_degrees": 360, "max_degrees": 1800},  # Over-rotated: more than target
        "LE": {"entry_angle_threshold": 30},  # Entry angle > 30 degrees (late/steep)
        "EE": {"entry_angle_threshold": 10},  # Entry angle < 10 degrees (early/shallow)
        "LS": {"spin_consistency_threshold": 0.6},  # Spin consistency < 0.6
        "LH": {"height_threshold": 50},  # Height < 50cm
        "PH": {"spin_consistency_threshold": 0.5},  # Inconsistent pike/twist
        "SA": {"approach_quality_threshold": 3.0},  # Overall approach score < 3.0
        "LK": {"overall_score_threshold": 3.0},  # Overall execution < 3.0
        "SK": {"entry_distance_threshold": 15},  # Entry distance > 15cm from center
    }

    # Phase associations
    PHASE_1_FAULTS = {"SA", "LH"}  # Approach/takeoff related
    PHASE_2_FAULTS = {"LE", "EE", "SK"}  # Entry related
    BOTH_PHASES_FAULTS = {"UR", "OR", "LS", "LK"}  # Can occur in either phase

    def __init__(self, db: Session):
        """Initialize detector with database session"""
        self.db = db

    def analyze_dive_execution(self, dive_id: int, metrics: Optional[Dict] = None) -> Dict:
        """
        Analyze dive execution and detect faults.

        Args:
            dive_id: ID of the dive to analyze
            metrics: Optional dict with execution metrics

        Returns:
            Dict with:
            - execution_score: 0.0-10.0
            - faults: List of detected ExecutionFault objects
            - adjusted_score: Score after fault deductions
            - phase1_analysis: Analysis of phase 1
            - phase2_analysis: Analysis of phase 2
        """
        dive = self.db.query(Dive).filter(Dive.id == dive_id).first()
        if not dive:
            raise ValueError(f"Dive {dive_id} not found")

        # Get FINA dive code for context
        fina_code = self.db.query(FINADiveCode).filter(
            FINADiveCode.dive_code == dive.dive_code
        ).first()

        # Detect faults in each phase
        phase1_faults = []
        phase2_faults = []
        total_points_deducted = Decimal("0.0")

        # Phase 1 analysis (hurdle + flight)
        if dive.phase1_numeric is not None:
            phase1_metrics = ExecutionMetrics(
                phase=1,
                rotation_degrees=metrics.get("phase1_rotation", 0) if metrics else 0,
                entry_distance_from_center=metrics.get("phase1_entry_distance", 0) if metrics else 0,
                entry_angle_degrees=metrics.get("phase1_entry_angle", 0) if metrics else 0,
                height_achieved=metrics.get("phase1_height", 100) if metrics else 100,
                spin_consistency=metrics.get("phase1_spin_consistency", 0.8) if metrics else 0.8,
                overall_score=athlete_score_10(dive.phase1_performance),
            )
            phase1_faults = self.detect_faults_by_phase(1, phase1_metrics, fina_code)

        # Phase 2 analysis (opening + entry)
        if dive.phase2_numeric is not None:
            phase2_metrics = ExecutionMetrics(
                phase=2,
                rotation_degrees=metrics.get("phase2_rotation", 0) if metrics else 0,
                entry_distance_from_center=metrics.get("phase2_entry_distance", 0) if metrics else 0,
                entry_angle_degrees=metrics.get("phase2_entry_angle", 0) if metrics else 0,
                height_achieved=metrics.get("phase2_height", 100) if metrics else 100,
                spin_consistency=metrics.get("phase2_spin_consistency", 0.8) if metrics else 0.8,
                overall_score=athlete_score_10(dive.phase2_performance),
            )
            phase2_faults = self.detect_faults_by_phase(2, phase2_metrics, fina_code)

        # Combine all faults
        all_faults = phase1_faults + phase2_faults

        # Calculate total points deducted
        for fault in all_faults:
            if fault.points_deducted:
                total_points_deducted += Decimal(str(fault.points_deducted))

        # Calculate adjusted score
        base_score = dive_score_10(dive)
        adjusted_score = max(Decimal("0.0"), Decimal(str(base_score)) - total_points_deducted)

        # Detect systematic patterns across both phases
        patterns = self.detect_systematic_patterns(dive_id, all_faults)

        return {
            "dive_id": dive_id,
            "execution_score": base_score,
            "adjusted_score": float(adjusted_score),
            "points_deducted": float(total_points_deducted),
            "faults": all_faults,
            "phase1_analysis": {
                "faults": phase1_faults,
                "count": len(phase1_faults),
            },
            "phase2_analysis": {
                "faults": phase2_faults,
                "count": len(phase2_faults),
            },
            "patterns": patterns,
        }

    def detect_faults_by_phase(
        self,
        phase: int,
        metrics: ExecutionMetrics,
        fina_code: Optional[FINADiveCode] = None,
    ) -> List[ExecutionFault]:
        """
        Detect faults in a specific phase of dive execution.

        Args:
            phase: Phase number (1 or 2)
            metrics: ExecutionMetrics for the phase
            fina_code: Optional FINADiveCode for context

        Returns:
            List of ExecutionFault objects
        """
        faults = []

        # Check each fault code applicable to this phase
        fault_codes_to_check = []
        if phase == 1:
            fault_codes_to_check = list(self.PHASE_1_FAULTS) + list(self.BOTH_PHASES_FAULTS)
        elif phase == 2:
            fault_codes_to_check = list(self.PHASE_2_FAULTS) + list(self.BOTH_PHASES_FAULTS)

        for fault_code in fault_codes_to_check:
            fault = self._check_fault_condition(fault_code, phase, metrics, fina_code)
            if fault:
                faults.append(fault)

        return faults

    def _check_fault_condition(
        self,
        fault_code: str,
        phase: int,
        metrics: ExecutionMetrics,
        fina_code: Optional[FINADiveCode] = None,
    ) -> Optional[ExecutionFault]:
        """
        Check if a specific fault condition exists.

        Returns: ExecutionFault object if fault detected, None otherwise
        """
        thresholds = self.FAULT_THRESHOLDS.get(fault_code)
        if not thresholds:
            return None

        detected = False
        raw_metric = None
        metric_threshold = None
        fault_description = None
        coaching_rec = None

        # Under-Rotation detection
        if fault_code == "UR" and fina_code:
            # Expected rotations based on dive code
            # twists field is half-twists, so divide by 2 to get full rotations worth
            twists_value = float(fina_code.twists) if fina_code.twists else 0
            expected_rotations = float(fina_code.rotations) + (twists_value / 2.0)
            expected_degrees = expected_rotations * 360
            # Under-rotated if actual < 90% of expected
            if metrics.rotation_degrees < expected_degrees * 0.9:
                detected = True
                raw_metric = metrics.rotation_degrees
                metric_threshold = expected_degrees * 0.9
                fault_description = f"Under-rotated dive: {metrics.rotation_degrees:.0f}° of {expected_degrees:.0f}° expected"
                coaching_rec = "Increase rotation speed or extend flight time to complete full rotations"

        # Over-Rotation detection
        elif fault_code == "OR" and fina_code:
            twists_value = float(fina_code.twists) if fina_code.twists else 0
            expected_rotations = float(fina_code.rotations) + (twists_value / 2.0)
            expected_degrees = expected_rotations * 360
            # Over-rotated if actual > 110% of expected
            if metrics.rotation_degrees > expected_degrees * 1.1:
                detected = True
                raw_metric = metrics.rotation_degrees
                metric_threshold = expected_degrees * 1.1
                fault_description = f"Over-rotated dive: {metrics.rotation_degrees:.0f}° of {expected_degrees:.0f}° expected"
                coaching_rec = "Reduce spin rate or entry angle to match dive requirements"

        # Late Entry detection
        elif fault_code == "LE":
            if metrics.entry_angle_degrees > thresholds.get("entry_angle_threshold", 30):
                detected = True
                raw_metric = metrics.entry_angle_degrees
                metric_threshold = thresholds.get("entry_angle_threshold", 30)
                fault_description = f"Late entry: angle {metrics.entry_angle_degrees:.1f}° (too steep)"
                coaching_rec = "Enter water sooner - reduce entry angle to be more vertical"

        # Early Entry detection
        elif fault_code == "EE":
            if metrics.entry_angle_degrees < thresholds.get("entry_angle_threshold", 10):
                detected = True
                raw_metric = metrics.entry_angle_degrees
                metric_threshold = thresholds.get("entry_angle_threshold", 10)
                fault_description = f"Early entry: angle {metrics.entry_angle_degrees:.1f}° (too shallow)"
                coaching_rec = "Allow more time in flight before entering water"

        # Lack of Spin/Twist detection
        elif fault_code == "LS":
            if metrics.spin_consistency < thresholds.get("spin_consistency_threshold", 0.6):
                detected = True
                raw_metric = metrics.spin_consistency
                metric_threshold = thresholds.get("spin_consistency_threshold", 0.6)
                fault_description = f"Inconsistent spin/twist: consistency {metrics.spin_consistency:.2f}"
                coaching_rec = "Focus on maintaining consistent spin rate throughout flight"

        # Lack of Height detection
        elif fault_code == "LH" and phase == 1:
            if metrics.height_achieved < thresholds.get("height_threshold", 50):
                detected = True
                raw_metric = metrics.height_achieved
                metric_threshold = thresholds.get("height_threshold", 50)
                fault_description = f"Insufficient height: {metrics.height_achieved:.0f}cm"
                coaching_rec = "Improve takeoff mechanics - stronger push from board/platform"

        # Pike/Twist Issue detection
        elif fault_code == "PH":
            if metrics.spin_consistency < thresholds.get("spin_consistency_threshold", 0.5):
                detected = True
                raw_metric = metrics.spin_consistency
                metric_threshold = thresholds.get("spin_consistency_threshold", 0.5)
                fault_description = f"Pike/twist position issue: consistency {metrics.spin_consistency:.2f}"
                coaching_rec = "Improve body position control during twists/pikes"

        # Starting Approach Issue detection
        elif fault_code == "SA" and phase == 1:
            if metrics.overall_score < thresholds.get("approach_quality_threshold", 3.0):
                detected = True
                raw_metric = metrics.overall_score
                metric_threshold = thresholds.get("approach_quality_threshold", 3.0)
                fault_description = f"Poor starting approach quality: score {metrics.overall_score:.1f}"
                coaching_rec = "Focus on approach consistency and board/platform utilization"

        # Lack of Control detection
        elif fault_code == "LK":
            if metrics.overall_score < thresholds.get("overall_score_threshold", 3.0):
                detected = True
                raw_metric = metrics.overall_score
                metric_threshold = thresholds.get("overall_score_threshold", 3.0)
                fault_description = f"Lack of overall control: score {metrics.overall_score:.1f}"
                coaching_rec = "Work on maintaining body control throughout entire dive"

        # Splash/Kiss detection
        elif fault_code == "SK" and phase == 2:
            if metrics.entry_distance_from_center > thresholds.get("entry_distance_threshold", 15):
                detected = True
                raw_metric = metrics.entry_distance_from_center
                metric_threshold = thresholds.get("entry_distance_threshold", 15)
                fault_description = f"Splash/Kiss: entry distance {metrics.entry_distance_from_center:.0f}cm from center"
                coaching_rec = "Improve entry alignment - aim for center line entry"

        if not detected:
            return None

        # Calculate severity
        severity, points = self.calculate_fault_severity(fault_code, raw_metric or 0.0)

        # Create ExecutionFault object
        fault = ExecutionFault(
            dive_id=None,  # Will be set when saved
            fault_code=fault_code,
            severity=severity,
            phase=phase,
            description=fault_description,
            coaching_recommendation=coaching_rec,
            fina_category=self._get_fina_category(fault_code),
            points_deducted=Decimal(str(points)),
            raw_metric=Decimal(str(raw_metric)) if raw_metric else None,
            metric_threshold=Decimal(str(metric_threshold)) if metric_threshold else None,
        )

        return fault

    def calculate_fault_severity(self, fault_code: str, raw_metric: float) -> Tuple[str, float]:
        """
        Calculate fault severity based on fault code and raw metric.

        Returns: (severity_level, points_deducted)
        """
        weight = self.FAULT_CODES.get(fault_code, {}).get("severity_weight", 1.0)

        if raw_metric == 0:
            # Default to MEDIUM severity if no metric provided
            return "MEDIUM", self.SEVERITY_MAPPING["MEDIUM"]["points_deducted"]

        # Determine severity based on metric magnitude
        metric_score = raw_metric * weight

        if metric_score >= self.SEVERITY_MAPPING["HIGH"]["min_threshold"]:
            return "HIGH", self.SEVERITY_MAPPING["HIGH"]["points_deducted"]
        elif metric_score >= self.SEVERITY_MAPPING["MEDIUM"]["min_threshold"]:
            return "MEDIUM", self.SEVERITY_MAPPING["MEDIUM"]["points_deducted"]
        else:
            return "LOW", self.SEVERITY_MAPPING["LOW"]["points_deducted"]

    def detect_systematic_patterns(self, dive_id: int, faults: Optional[List[ExecutionFault]] = None) -> Dict:
        """
        Detect systematic patterns in execution faults across multiple dives.

        Args:
            dive_id: Primary dive ID for context
            faults: Optional list of faults (if not provided, will query database)

        Returns:
            Dict with pattern analysis
        """
        if faults is None:
            # Query all faults for this dive
            faults = self.db.query(ExecutionFault).filter(
                ExecutionFault.dive_id == dive_id
            ).all()

        # Aggregate fault codes
        fault_codes = {}
        severity_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

        for fault in faults:
            fault_codes[fault.fault_code] = fault_codes.get(fault.fault_code, 0) + 1
            severity_counts[fault.severity] += 1

        # Identify patterns
        patterns = {
            "total_faults": len(faults),
            "fault_codes": fault_codes,
            "severity_distribution": severity_counts,
            "is_systematic": len(faults) >= 2,  # 2+ faults suggests systematic issue
            "primary_issue": max(fault_codes.items(), key=lambda x: x[1])[0] if fault_codes else None,
        }

        return patterns

    def save_faults_for_dive(self, dive_id: int, faults: List[ExecutionFault]) -> List[ExecutionFault]:
        """
        Save execution faults to database for a dive.

        Args:
            dive_id: ID of the dive
            faults: List of ExecutionFault objects (not yet persisted)

        Returns:
            List of saved ExecutionFault objects
        """
        saved_faults = []

        for fault in faults:
            fault.dive_id = dive_id

            # Check for existing fault with same code and phase
            existing = self.db.query(ExecutionFault).filter(
                ExecutionFault.dive_id == dive_id,
                ExecutionFault.fault_code == fault.fault_code,
                ExecutionFault.phase == fault.phase,
            ).first()

            if existing:
                # Update existing fault
                existing.severity = fault.severity
                existing.description = fault.description
                existing.coaching_recommendation = fault.coaching_recommendation
                existing.points_deducted = fault.points_deducted
                existing.raw_metric = fault.raw_metric
                existing.metric_threshold = fault.metric_threshold
                self.db.commit()
                self.db.refresh(existing)
                saved_faults.append(existing)
            else:
                # Create new fault
                self.db.add(fault)
                saved_faults.append(fault)

        self.db.commit()

        # Refresh all saved faults
        for fault in saved_faults:
            self.db.refresh(fault)

        return saved_faults

    def _get_fina_category(self, fault_code: str) -> str:
        """Get FINA scoring category for a fault"""
        fina_categories = {
            "UR": "Insufficient Rotation - FINA Execution Deduction",
            "OR": "Excess Rotation - FINA Execution Deduction",
            "LE": "Late Entry - Execution Deduction",
            "EE": "Early Entry - Execution Deduction",
            "LS": "Lack of Spin - Execution Deduction",
            "LH": "Lack of Height - Execution Deduction",
            "PH": "Poor Position - Execution Deduction",
            "SA": "Poor Approach - Execution Deduction",
            "LK": "Loss of Control - Execution Deduction",
            "SK": "Splash/Kiss - Minor Deduction",
        }
        return fina_categories.get(fault_code, "Execution Deduction")

    def get_fault_summary_for_dive(self, dive_id: int) -> Dict:
        """
        Get summary of all faults for a dive.

        Args:
            dive_id: ID of the dive

        Returns:
            Dict with fault summary
        """
        faults = self.db.query(ExecutionFault).filter(
            ExecutionFault.dive_id == dive_id
        ).all()

        if not faults:
            return {
                "dive_id": dive_id,
                "total_faults": 0,
                "total_points_deducted": 0.0,
                "faults": [],
            }

        total_points = sum(float(f.points_deducted or 0) for f in faults)

        return {
            "dive_id": dive_id,
            "total_faults": len(faults),
            "total_points_deducted": total_points,
            "faults": [
                {
                    "fault_id": f.id,
                    "fault_code": f.fault_code,
                    "severity": f.severity,
                    "phase": f.phase,
                    "description": f.description,
                    "coaching_recommendation": f.coaching_recommendation,
                    "fina_category": f.fina_category,
                    "points_deducted": float(f.points_deducted or 0),
                }
                for f in faults
            ],
        }
