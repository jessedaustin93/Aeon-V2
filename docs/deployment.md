# Deploying Aeon-V2 on the T5810

## Prerequisites

- Python 3.11+, Node 18+ (for the web build), git.
- LM Studio running with the chat/deep/embed models loaded, server on `:1234`.
- Tailscale (clients reach the server over the tailnet).

## Install

```bash
cd ~ && git clone https://github.com/jessedaustin93/Aeon-V2
cd Aeon-V2 && ./deploy/install.sh
```

The installer creates the venv, installs the server, scaffolds
`~/aeon-data/`, seeds Aeon's default runtime skills, writes
`~/aeon-data/aeon.env` from the example, builds the web app, and installs the
systemd user services.

## Configure

Edit `~/aeon-data/aeon.env`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # -> AEON_API_TOKEN
```

Set the token, confirm the model names match LM Studio, and point
`AEON_V1_MASTER_VAULT_PATH` at the vault checkout. Fill in `AEON_MESH_*` if this
host joins the Agent Mesh.

## Run

```bash
systemctl --user enable --now aeon-server        # API + web on :8900
systemctl --user enable --now aeon-mesh-peer     # optional: mesh peer
systemctl --user status aeon-server
```

Open `http://t5810:8900` from any tailnet device, go to **Settings**, paste the
token. On a phone, use "Add to Home Screen" to install the PWA.

## Updating

```bash
cd ~/Aeon-V2 && git pull && ./deploy/install.sh
systemctl --user restart aeon-server aeon-mesh-peer
```

## Security notes

- The API refuses remote connections unless `AEON_API_TOKEN` is set; keep it set.
- Bind the tailnet only — do not port-forward `:8900` to the public internet.
- `shell_run`, `ssh_run`, and `mesh_post` always require in-UI approval.
- `ssh_run` only targets aliases from `AEON_SSH_HOSTS` or the service user's
  `~/.ssh/config`; SSH private keys stay outside the repo and data directory.
- The mesh peer runs with tools disabled unless `AEON_MESH_ENABLE_TOOLS=1`.
