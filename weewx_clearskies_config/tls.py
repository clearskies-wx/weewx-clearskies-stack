import datetime
import hashlib
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _build_san_list(bind_addresses: list[str]) -> list[x509.GeneralName]:
    san: list[x509.GeneralName] = []
    seen: set[str] = set()

    def _add_dns(name: str) -> None:
        if name not in seen:
            seen.add(name)
            san.append(x509.DNSName(name))

    def _add_ip(addr: str) -> None:
        if addr not in seen:
            seen.add(addr)
            try:
                san.append(x509.IPAddress(ipaddress.ip_address(addr)))
            except ValueError:
                pass

    for addr in bind_addresses:
        # Strip brackets from IPv6 literals like [::1]
        addr = addr.strip("[]")
        try:
            ip = ipaddress.ip_address(addr)
            _add_ip(str(ip))
        except ValueError:
            # Treat as hostname
            _add_dns(addr)

    # Always include the loopback entries and localhost DNS name
    _add_dns("localhost")
    _add_ip("127.0.0.1")
    _add_ip("::1")

    return san


def generate_self_signed_cert(
    bind_addresses: list[str],
    cert_path: Path,
    key_path: Path,
) -> None:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Pick subject CN from first address (strip brackets for IPv6)
    subject_cn = bind_addresses[0].strip("[]") if bind_addresses else "localhost"

    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])
    san_list = _build_san_list(bind_addresses)

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        key_path.chmod(0o600)
    except NotImplementedError:
        # Windows does not support POSIX chmod
        pass


def _cert_san_matches(cert_path: Path, bind_addresses: list[str]) -> bool:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    try:
        existing_san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return False

    existing_names: set[str] = set()
    for entry in existing_san.value:
        if isinstance(entry, x509.DNSName):
            existing_names.add(entry.value)
        elif isinstance(entry, x509.IPAddress):
            existing_names.add(str(entry.value))

    required = _build_san_list(bind_addresses)
    required_names: set[str] = set()
    for entry in required:
        if isinstance(entry, x509.DNSName):
            required_names.add(entry.value)
        elif isinstance(entry, x509.IPAddress):
            required_names.add(str(entry.value))

    return required_names.issubset(existing_names)


def load_or_generate_cert(
    bind_addresses: list[str],
    config_dir: Path,
) -> tuple[Path, Path]:
    cert_path = config_dir / "tls.crt"
    key_path = config_dir / "tls.key"

    if cert_path.exists() and key_path.exists() and _cert_san_matches(cert_path, bind_addresses):
        return cert_path, key_path

    config_dir.mkdir(parents=True, exist_ok=True)
    generate_self_signed_cert(bind_addresses, cert_path, key_path)
    return cert_path, key_path


def get_cert_fingerprint(cert_path: Path) -> str:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    der = cert.public_bytes(serialization.Encoding.DER)
    digest = hashlib.sha256(der).hexdigest()
    # Format as colon-separated pairs for readability
    return ":".join(digest[i : i + 2].upper() for i in range(0, len(digest), 2))
