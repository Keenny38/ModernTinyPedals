# App version (MAJOR.MINOR.PATCH), set by the release workflow from commits since last release:
# minor for new features (commit titles starting with "Add"), patch for fixes & changes
__version__ = "0.10.0"
# Development version tag (set to "" for release-version)
DEVELOPMENT = ""
# Setting format version, stored in presets and used by setting_preupdate migrations.
# Kept on the TinyPedal numbering (independent from app version), so presets from
# TinyPedal 2.x keep loading. Raise it only with a new migration in setting_preupdate.
SETTING_VERSION = "2.50.2"
