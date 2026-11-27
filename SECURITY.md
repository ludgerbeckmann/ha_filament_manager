# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please report a vulnerability privately through GitHub's
[private vulnerability reporting](https://github.com/ludgerbeckmann/ha_filament_manager/security/advisories/new)
instead of opening a public issue. Include the version, a short description,
and how to reproduce it. Remove private details from any logs first.

## Scope

Filament Manager is a Home Assistant custom integration that keeps a local
filament inventory in Home Assistant's own storage; it runs no server of its
own. Optionally it reads the state of the Bambu Lab integration and, if you add
your Bambu Cloud account, reads spool data from the Bambu Cloud (read-only). For
that account only the e-mail address, the region and the access token are kept
in the Home Assistant config entry; the password is used for the login and is
not stored. Home Assistant's own security (its users, network exposure and
backups) is outside the scope of this policy.
