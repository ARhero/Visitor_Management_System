"""Make a self-signed HTTPS certificate for serving VMS on an IP address.

    uv run python -m scripts.make_cert 203.0.113.10 192.168.1.12

Writes .certs/cert.pem and .certs/key.pem (in api/), valid for 2 years, for every IP
address or host name given, plus localhost. Browsers warn about it once per device
("not private"); after proceeding, everything except phone alerts works. A domain with a
real certificate (e.g. Let's Encrypt) avoids the warning.
"""

import ipaddress
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

OUT = Path(__file__).resolve().parents[1] / ".certs"


def main(names: list[str]) -> None:
    if not names:
        raise SystemExit("Give the public IP address (and any others), e.g. 203.0.113.10")
    sans: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for n in names:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            sans.append(x509.DNSName(n))
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"VMS {names[0]}")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=730))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    OUT.mkdir(exist_ok=True)
    (OUT / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (OUT / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    print(f"Wrote {OUT / 'cert.pem'} and key.pem for: localhost, {', '.join(names)}")


if __name__ == "__main__":
    main(sys.argv[1:])
