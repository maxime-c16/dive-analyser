# Round5 factual checks and unresolved observations

- Profile Activity/Achievements mirroring: current MemberProfile.tsx renders distinct ActivityTimeline/AchievementsPanel, retains visited panels with hidden={key!==tab}; existing regression verifies achievements hidden after switching away. Added explicit scoped hidden CSS protection. Real browser verification remains pending due auth/me401. Do not classify as proven fixed or dismiss the observed screenshots.
- Muted contrast: prior professional-shell palette sets #afbcc7; root fallback is #98a2aa. Review subjective contrast scores remain unchanged. Corrected scope now #c0cbd3 with stronger border, awaiting actual screenshots and review. No accessibility certification.
- Different trend directions: overview compares six-week medians; details regression uses the selected filtered window. Corrected details makes that window explicit; no analytics formula altered.
- Identical imported timestamps and null dive_number remain source truth. Canonical IDs are primary; no invented attempt time/sequence.
- Missing council coverage never inherits a numeric pass from another size or family.
