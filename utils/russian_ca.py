"""SSL context trusting the Минцифры (Russian Trusted) root CA plus certifi.

Max serves its TLS certificate selectively by client route: a public Let's
Encrypt cert to clients it sees as foreign, and a Минцифры-issued cert (absent
from certifi and from a vanilla system trust store) to Russia-routed clients —
which is how the bot's host reaches Max. Both the aiomax API session and the
httpx file-download client must therefore trust the Минцифры root in addition
to the public bundle. Only the root is needed: like T-Банк's acquiring (see
payment.py), Max sends the intermediate in the handshake, so the root is enough
as a trust anchor. certifi as the base keeps the public Let's Encrypt / HARICA
chains valid regardless of which cert Max returns.
"""
import ssl
from pathlib import Path

import certifi

_CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
SSL_CONTEXT.load_verify_locations(_CERTS_DIR / "russian_trusted_root_ca.pem")
