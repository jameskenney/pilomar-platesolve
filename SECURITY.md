# Security policy

## Supported versions

Only the latest version on the `main` branch is supported. Please update with
`git pull` before reporting a problem.

## Reporting a vulnerability

Please **don't open a public issue** for a security problem.

Report it privately instead: on the repository's **Security** tab, click
**Report a vulnerability**. Include what you found, how to reproduce it, and
which version (`pilomar-ps --version`) and Pi-lomar version you used.

This is a hobby project maintained in spare time. You can expect an
acknowledgement within about a week, and a fix as soon as is practical. You'll
be credited in the fix unless you'd rather not be.

## Scope

pilomar-platesolve runs locally on a Raspberry Pi. Useful things to know when
judging a report:

* It opens no network ports and needs no internet connection after install.
* It runs `solve-field`, `rpicam-still` and `tmux` as the logged-in user.
* In `tmux` mode it types menu choices into a Pi-lomar session running as the
  same user.
* It reads Pi-lomar's files and writes only into its own `data` folder.
* It uses only Python's standard library, plus OpenCV from the system if present.

Reports about how it handles files, pictures or settings it reads, the
commands it runs, or the keys it sends to Pi-lomar are all in scope.
