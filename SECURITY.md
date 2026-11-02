# Security policy

Do not report vulnerabilities in a public issue. Use GitHub's private vulnerability
reporting feature for this repository (Security → Advisories → Report a vulnerability).
If private reporting is unavailable, contact the repository maintainer through a private
channel listed on the repository and include only the details needed to investigate.

Never commit `.env` or share its contents. Rotate any credentials that may have been exposed.
Do not expose database, model-server, gateway, or WebUI ports to the internet; follow the
README's localhost binding and Cloudflare Access guidance.
