"""
Generate a root CA + a single leaf cert covering every hostname the 0.29
client talks to. Install certs/ca.crt on the device/emulator (as a trusted
CA) and the client will accept our TLS for these hosts.

Run:  py gen_certs.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CERTS = os.path.join(HERE, "certs")

SANS = [
    # The in-game Settings "support" button opens pokemongo.zendesk.com/hc in the
    # phone's browser. We redirect that host and serve the Help Center there, so
    # the cert has to cover it -- signed by the same CA the phone already trusts.
    "pokemongo.zendesk.com",
    "*.zendesk.com",
    "sso.pokemon.com",
    "*.pokemon.com",
    "pokemon.com",
    "pgorelease.nianticlabs.com",
    "holo.nianticlabs.com",
    "www.nianticlabs.com",
    "*.nianticlabs.com",
    "nianticlabs.com",
]


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def main():
    os.makedirs(CERTS, exist_ok=True)
    p = lambda n: os.path.join(CERTS, n)

    # 1) Root CA (with explicit CA basicConstraints + keyUsage; strict
    #    verifiers and Android both want these present).
    #    REUSED if it already exists. Regenerating it would invalidate the CA
    #    every phone has already installed, breaking every client at once --
    #    which makes adding a hostname to SANS a trap. Delete certs/ca.* by hand
    #    if you really want a fresh root.
    if os.path.exists(p("ca.crt")) and os.path.exists(p("ca.key")):
        print("keeping the existing CA (phones already trust it)")
    else:
        run("openssl", "genrsa", "-out", p("ca.key"), "2048")
        run("openssl", "req", "-x509", "-new", "-nodes", "-key", p("ca.key"),
            "-sha256", "-days", "3650", "-out", p("ca.crt"),
            "-subj", "/C=US/O=PoGO Private Server/CN=PoGO Private CA",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        print("created a NEW root CA -- every phone must reinstall ca.crt")

    # 2) Leaf key + CSR
    run("openssl", "genrsa", "-out", p("server.key"), "2048")
    run("openssl", "req", "-new", "-key", p("server.key"), "-out", p("server.csr"),
        "-subj", "/C=US/O=PoGO Private Server/CN=pgorelease.nianticlabs.com")

    # 3) Sign leaf with SAN extensions
    ext = ("subjectAltName=" + ",".join(f"DNS:{h}" for h in SANS) + "\n"
           "extendedKeyUsage=serverAuth\n"
           "keyUsage=critical,digitalSignature,keyEncipherment\n"
           "basicConstraints=CA:FALSE\n")
    with tempfile.NamedTemporaryFile("w", suffix=".ext", delete=False) as f:
        f.write(ext)
        extfile = f.name
    try:
        run("openssl", "x509", "-req", "-in", p("server.csr"),
            "-CA", p("ca.crt"), "-CAkey", p("ca.key"), "-CAcreateserial",
            "-out", p("server.crt"), "-days", "3650", "-sha256",
            "-extfile", extfile)
    finally:
        os.unlink(extfile)

    print("Wrote:")
    for n in ("ca.crt", "ca.key", "server.crt", "server.key"):
        print("  certs/" + n)
    print("\nInstall certs/ca.crt on your device/emulator as a trusted CA.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print("openssl failed:", e, file=sys.stderr)
        sys.exit(1)
