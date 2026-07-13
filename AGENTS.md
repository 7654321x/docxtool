# Agent Notes

## GitHub Repository

This project is pushed to:

```text
git@github.com:7654321x/docxtool.git
https://github.com/7654321x/docxtool.git
```

Default branch:

```text
main
```

## SSH Key Setup

The private key is stored on Windows at:

```text
/mnt/c/Users/94575/.ssh/id_ed25519
```

Do not commit the private key or paste its contents into any project file.

OpenSSH inside WSL rejects keys under `/mnt/c` when Windows exposes them as
world-readable. Copy the key into the WSL user SSH directory and restrict
permissions before pushing:

```bash
mkdir -p "$HOME/.ssh"
cp /mnt/c/Users/94575/.ssh/id_ed25519 "$HOME/.ssh/id_ed25519_github"
cp /mnt/c/Users/94575/.ssh/id_ed25519.pub "$HOME/.ssh/id_ed25519_github.pub"
chmod 700 "$HOME/.ssh"
chmod 600 "$HOME/.ssh/id_ed25519_github"
chmod 644 "$HOME/.ssh/id_ed25519_github.pub"
```

Verify GitHub authentication:

```bash
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  -i "$HOME/.ssh/id_ed25519_github" git@github.com
```

Expected result includes:

```text
Hi 7654321x! You've successfully authenticated, but GitHub does not provide shell access.
```

## Push Workflow

Run commands from the project directory:

```bash
cd /mnt/d/PycharmProjects/project8/docxtool
git status --short --branch
git add .
git commit -m "Describe the change"
GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_ed25519_github -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
  git push origin main
```

If the remote is missing or incorrect, set it to:

```bash
git remote set-url origin git@github.com:7654321x/docxtool.git
```

## Local Git Identity

Use the GitHub account identity for commits from this repository:

```bash
git config user.name "7654321x"
git config user.email "7654321x@users.noreply.github.com"
```

This sets identity only for the current repository, not globally.

