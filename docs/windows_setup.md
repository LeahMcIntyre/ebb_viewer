# Windows setup guide

This guide gets `ebb-viewer` running on a Windows PC starting from nothing. You do not need to know
whether Miniconda, Git, or Python is already installed — Step 1 checks, and each step says what to do
either way.

Everything below is typed into a terminal window. Lines in grey boxes are commands: type or paste them
exactly, then press **Enter**.

---

## Step 1 — Check what you already have

Open the **Start menu**, type **Anaconda Prompt**, and open it.

- **It opens** (a black window with `(base)` at the start of the line): Miniconda/Anaconda is already
  installed. Skip Step 2 and go to Step 3.
- **Nothing found:** open **Command Prompt** instead (Start menu → type `cmd`), then run:

  ```bat
  conda --version
  ```

  - Prints something like `conda 24.x.x` → conda is installed. Use Command Prompt for the rest of this
    guide, and if later commands fail with "conda is not recognized", use Anaconda Prompt.
  - Prints `'conda' is not recognized...` → conda is not installed. Go to Step 2.

---

## Step 2 — Install Miniconda (skip if Step 1 found conda)

1. Go to <https://www.anaconda.com/download> and scroll to **Miniconda**
   (or search "Miniconda install"). Download the **Windows 64-bit** installer.
2. Run the downloaded `.exe`.
   - Choose **Just Me** (no admin rights needed).
   - Keep the default install location.
   - Leave the checkboxes at their defaults. Ignore the "not recommended" warning about adding to PATH
     — you will use *Anaconda Prompt*, which doesn't need it.
3. Finish the installer, then open **Anaconda Prompt** from the Start menu. You should see `(base)` at
   the start of the line.

---

## Step 3 — Check for Git (and install it if missing)

In Anaconda Prompt:

```bat
git --version
```

- Prints `git version 2.x.x` → go to Step 4.
- Prints `'git' is not recognized` → install **Git for Windows** from <https://git-scm.com/download/win>
  (accept the default options). Close and reopen Anaconda Prompt, then run `git --version` again to
  confirm.

  Use Git for Windows rather than `conda install git`: because the repository is private, you need the
  browser sign-in that Git for Windows provides (Git Credential Manager). The conda version doesn't
  include it, and GitHub no longer accepts account passwords on the command line.

---

## Step 4 — Get access to the GitHub repository

The repository is at <https://github.com/LeahMcIntyre/ebb_viewer>.

1. If you don't have a GitHub account, create one at <https://github.com/signup>.
2. If the repository is **private**, ask Leah to add your GitHub username as a collaborator, then accept
   the invitation email (or visit <https://github.com/notifications>).
3. You will be asked to sign in the first time you clone (Step 5). A browser window opens for you to log
   in — this is normal. No SSH keys are needed.

---

## Step 5 — Download (clone) the code

Pick a folder to keep the project in. This example uses `C:\Users\<you>\Developer`:

```bat
mkdir %USERPROFILE%\Developer
cd %USERPROFILE%\Developer
git clone https://github.com/LeahMcIntyre/ebb_viewer.git
cd ebb_viewer
```

If a sign-in window appears, sign in to GitHub. If you see `repository not found`, you are either not
signed in to the right account or haven't been given access (Step 4).

**Which branch?** The default branch (`main`) is the stable release. If Leah asks you to test newer
work, switch to it with `git checkout dev`.

---

## Step 6 — Create the Python environment

The repository includes an environment file listing every dependency. From inside the `ebb_viewer`
folder:

```bat
conda env create -f envs\ebb-dev.yml
```

This takes a few minutes. When it finishes, activate the environment:

```bat
conda activate ebb-dev
```

The start of your prompt should change from `(base)` to `(ebb-dev)`.

> If conda complains about **Terms of Service** for `defaults` channels, run
> `conda config --add channels conda-forge` and `conda config --set channel_priority strict`, then retry.
> The environment file only uses `conda-forge`.

---

## Step 7 — Install ebb-viewer itself

Still in the `ebb_viewer` folder with `(ebb-dev)` active:

```bat
pip install -e .
```

"Editable" mode means that when you later pull updates, they take effect immediately.

---

## Step 8 — Run it

```bat
ebb-viewer
```

The ebb-viewer window should open. When you pick a project folder, it should contain your raw EDF
files; the app creates the `standard/`, `spindle_edfs/`, and `psd/` folders and a `manifest.json`
inside it.

### Every time after this

Open **Anaconda Prompt** and run:

```bat
conda activate ebb-dev
ebb-viewer
```

---

## Updating to the latest version

```bat
cd %USERPROFILE%\Developer\ebb_viewer
conda activate ebb-dev
git pull
pip install -e .
```

If `git pull` reports changes to `envs\ebb-dev.yml`, also run:

```bat
conda env update -f envs\ebb-dev.yml --prune
```

---

## Verifying the install (optional)

```bat
pytest
```

All tests should pass.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `'conda' is not recognized` | Use **Anaconda Prompt** from the Start menu, not Command Prompt/PowerShell. |
| `'git' is not recognized` | Install Git for Windows (Step 3), then reopen Anaconda Prompt. |
| Git asks for a username/password in the terminal instead of opening a browser | You have a Git without Credential Manager (e.g. from conda). Install Git for Windows (Step 3), reopen the prompt, and retry the clone. |
| `repository not found` / `Authentication failed` | You're not signed in to the right GitHub account, or you haven't been added as a collaborator (Step 4). |
| `EnvironmentNameNotFound` on `conda activate ebb-dev` | Step 6 didn't finish. Re-run `conda env create -f envs\ebb-dev.yml` from the `ebb_viewer` folder. |
| `'ebb-viewer' is not recognized` | The environment isn't active (`(ebb-dev)` missing from the prompt) or Step 7 was skipped. |
| Window never appears / Qt "platform plugin" error | Make sure you're in the `ebb-dev` environment, not `base`. Re-run `pip install -e .`. |
| PowerShell blocks `conda activate` | Use **Anaconda Prompt**, or run `conda init powershell` once and reopen PowerShell. |
| Environment creation is very slow or fails on solving | Run `conda update -n base conda`, then retry Step 6. |
