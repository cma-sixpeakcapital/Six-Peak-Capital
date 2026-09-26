"""Weekly Scorecard: reads the published "Six Peak L10 Data" Google Sheet,
validates it, and computes Red / Yellow / Green for the portal.

Modules:
    sheet    fetch the published CSV tabs (no credentials; Publish-to-web link)
    parse    turn CSV text into a validated model + a list of row errors
    ryg      target resolution (incl. glidepaths), colors, streaks, the view
    service  caching, the Tuesday meeting freeze, manual refresh
"""
