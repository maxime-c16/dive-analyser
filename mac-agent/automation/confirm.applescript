use framework "Foundation"
use scripting additions

property statePath : "__STATE_DIR__"

on readJSON(filePath)
    set jsonData to current application's NSData's dataWithContentsOfFile:filePath
    if jsonData is missing value then error "Missing request"
    set obj to current application's NSJSONSerialization's JSONObjectWithData:jsonData options:0 |error|:(missing value)
    if obj is missing value then error "Invalid request"
    return obj
end readJSON

on verifyLiveRequest(marker, helperPID, token)
    set currentDate to current application's NSDate's |date|()
    set age to (currentDate's timeIntervalSince1970() as real) - ((marker's objectForKey:"created_at") as real)
    if age < 0 or age > 20 then error "Expired request"
    set helperCommand to do shell script "/bin/ps -p " & helperPID & " -o command="
    if helperCommand does not contain ("-m src.photos_cleanup --automated-batch " & token) then error "Wrong helper process"
end verifyLiveRequest

on run
    set token to ""
    set outcome to "refused"
    set failureNumber to 0
    try
        set request to my readJSON(statePath & "/request.json")
        set token to (request's objectForKey:"nonce") as text
        set processRecord to current application's NSMutableDictionary's dictionary()
        processRecord's setObject:token forKey:"nonce"
        set ownProcess to current application's NSProcessInfo's processInfo()
        processRecord's setObject:(ownProcess's processIdentifier()) forKey:"pid"
        set processData to current application's NSJSONSerialization's dataWithJSONObject:processRecord options:0 |error|:(missing value)
        processData's writeToFile:(statePath & "/ui-process.json") atomically:true
        set requestedAction to (request's objectForKey:"action") as text
        set helperPID to (request's objectForKey:"pid") as integer
        if length of token is not 32 then error "Invalid nonce"
        if requestedAction is "inspect" then
            tell application "System Events"
                if exists application process "UserNotificationCenter" then
                    tell application process "UserNotificationCenter"
                        if (count of windows) is not 0 then error "Existing confirmation"
                    end tell
                end if
            end tell
            set outcome to "clear"
        else if requestedAction is "lock" then
            tell application "System Events" to keystroke "q" using {control down, command down}
            set outcome to "locked"
        else if requestedAction is "confirm" or requestedAction is "cancel" then
            if helperPID < 2 then error "Invalid helper"
            set marker to my readJSON(statePath & "/" & token & ".armed")
            if (marker's objectForKey:"nonce") as text is not token then error "Wrong marker"
            if (marker's objectForKey:"pid") as integer is not helperPID then error "Wrong PID"
            if (marker's objectForKey:"count") as integer is not 1 then error "Wrong batch"
            my verifyLiveRequest(marker, helperPID, token)
            set expectedBody to "This video will be deleted from iCloud Photos on all your devices. It will be in Recently Deleted for 30 days."
            tell application "System Events"
                repeat 40 times
                    if exists application process "UserNotificationCenter" then
                        tell application process "UserNotificationCenter"
                            if (count of windows) > 0 then exit repeat
                        end tell
                    end if
                    delay 0.2
                end repeat
                tell application process "UserNotificationCenter"
                    if (count of windows) is not 1 then error "Expected one confirmation"
                    if (count of static texts of window 1) is not 2 then error "Unexpected structure"
                    if (value of static text 1 of window 1) is not "" then error "Unexpected heading"
                    if (value of static text 2 of window 1) is not expectedBody then error "Unexpected body"
                    if (get name of every button of window 1) is not {"Don’t Allow", "Delete"} then error "Unexpected buttons"
                    if not (enabled of button "Delete" of window 1) then error "Disabled button"
                    my verifyLiveRequest(marker, helperPID, token)
                    if requestedAction is "confirm" then
                        click button "Delete" of window 1
                    else
                        click button "Don’t Allow" of window 1
                    end if
                end tell
            end tell
            if requestedAction is "confirm" then
                set outcome to "clicked"
            else
                set outcome to "cancelled"
            end if
        else
            error "Unknown action"
        end if
    on error number errorCode
        set failureNumber to errorCode
    end try
    set response to current application's NSMutableDictionary's dictionary()
    response's setObject:token forKey:"nonce"
    response's setObject:outcome forKey:"result"
    response's setObject:failureNumber forKey:"error_number"
    set output to current application's NSJSONSerialization's dataWithJSONObject:response options:0 |error|:(missing value)
    output's writeToFile:(statePath & "/result.json") atomically:true
end run
