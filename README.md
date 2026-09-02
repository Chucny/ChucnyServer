# ChucnyServer


<img src="screenshots/03_SCROT" style="width: 200px;"></img>
<img src="screenshots/02_SCROT" style="width: 200px;"></img>
<img src="screenshots/01_SCROT.png" style="width: 350px;"></img>
## 📁 Overview
**ChucnyServer** is an open source **MITM** (man in the middle) **0.29.0 Pokemon GO server** made in Python.

<a href="https://chucny.github.io"><strong>The ChucnyServer website</strong></a>

## 🖥️ How to Run
1. Run the **DOWNLOAD.py** script inside `/scripts`. Alternatively, download the dependencies manually (recommended).
2. Get the assets **(DM @chucny on Discord to get them if you don't have them)**.
3. Run the script called **`__main__.py`** inside `/chucnyserver`.
4. Install the Pokemon GO 0.29.0 APK onto your phone (note: it's a 32-bit APK).
5. Install the file **CA.crt** inside the `/chucnyserver/certs` folder as a **CA certificate** on your phone.
6. Go to your Wi-Fi settings and change your **DNS** to the IP shown in the server output.
7. Open the **Pokemon GO app** and tap on **Pokemon Trainer Club**.
8. Enter any username and password.
9. You are now in!

## ⌨️ How to Use the Terminal Manager
*Remember: The terminal manager is still full of bugs and is in Beta.*

1. Run **terminal.py** (do not run `__main__.py`).
---
## 🛠️ ChucnyServer Patcher – Linux Installation Guide
This guide will help you set up your Linux environment and patch the **Pokémon GO 0.29-0.35 APK** to remove certificate pinning and allow it to connect to **ChucnyServer**. The patcher supports versions 0.29.0 all the way up to 0.35.0 without breaking the app or server.

### 📋 Prerequisites
To run the patcher interface and successfully re-pack the APK file, your system must have the following tools installed:
* **Java Development Kit (JDK)** – Required for signing and aligning the modified APK (`keytool` and `apksigner`).
* **Node.js (v14 or newer)** – Required to run the patching core engine.
* **apk-mitm** – The command-line utility that handles the certificate injection process.

### 🐧 Linux Installation Steps
Open your terminal and execute the commands corresponding to your Linux distribution:

#### For Ubuntu / Debian / Mint
```bash
# Update package repositories
sudo apt update

# Install Java (OpenJDK 17 is recommended)
sudo apt install -y openjdk-17-jdk

# Install Node.js and NPM
sudo apt install -y nodejs npm
```

#### For Arch Linux
```bash
sudo pacman -Syu
sudo pacman -S jdk17-openjdk nodejs npm
```

#### For Fedora
```bash
sudo dnf update
sudo dnf install java-17-openjdk-devel nodejs
```

#### Install apk-mitm (Globally via NPM)
Once Node.js and its package manager are installed, install `apk-mitm` globally on your machine:
```bash
sudo npm install -g apk-mitm
```

### ⚙️ How to Use the Patcher

<img src="screenshots/04_SCROT.png" style="width: 350px;"></img>

With all dependencies installed, you can proceed to modify your game client using either the graphical interface or the command line.

#### Option A: Using the ChucnyServer Patcher (UI)
1. Open the `/patcher/patcher.py` file in your preferred web browser.
2. Click on the **"Select APK File"** button (or simply drag and drop your downloaded Pokémon GO 0.29.0 APK into the designated area).
3. Click the **"Start Patching Process"** button.
4. The interface will interact with your system utilities (`java`, `node`, `apk-mitm`) to decompile, inject network security overrides, and re-sign the package.
5. Save the output file, usually generated as `app-name-patched.apk`.

#### Option B: Using the Terminal Directly
If you prefer bypassing the web UI and running the process manually:
```bash
apk-mitm path/to/pokemon-go-0.29.0.apk
```
*This command will output a newly modified file with the `-patched.apk` suffix in the same directory.*

### 📱 Final Device Configuration
1. Transfer your newly generated patch file (`-patched.apk`) onto your Android device and install it.
2. Install the `CA.crt` file (found inside your server directory at `/chucnyserver/certs`) onto your phone storage as a trusted **CA Certificate** via system security settings.
3. Head over to your phone's Wi-Fi configuration and change your primary **DNS** server to match the IP address outputted by your active ChucnyServer terminal.
4. Launch Pokémon GO, select the **"Pokemon Trainer Club"** login option, enter any username/password combination, and enjoy your server!
---

## 💾 MariaDB
Note: MariaDB isn't needed, the server will save everything in <code>json</code> files. This feature still allows you to back up players, pokestops and gyms.
**How to use**:
1. Install MariaDB
2. Put the MariaDB port, password, name and username in <code>config.py</code>
3. Run the MariaDB database
4. Run <code>database.py</code> and type <code>/help</code> for help with commands

## 📝 Features
* **World Manager**: Manage spawns, PokeStops, gyms, events, and more.
* **Raids**: Defeat a powerful boss at a gym. Once defeated, it spawns next to the gym for you to catch.
* **Community Day & Events**: Play different community days.
* **Gym Battles**: Battle Pokémon in gyms!
* **Automatic PokeStop Import**: Import up to 10,000 PokeStops at once via the OSM API!
* **Terminal Manager**: An alternative to the graphical World Manager served at `localhost:8080`. It is still in beta and contains bugs.

## 🗄️ How to Get Assets
1. Send a friend request to me at **@chucny** on Discord if you do not have the assets.
2. I will respond within a couple of hours to days and provide you with a download link to the assets.
3. **Download** the assets.
4. Paste the 152 asset files directly into the `/chucnyserver/assets` folder.
5. Run the server.

## ⚖️ Asset Distribution Disclaimer
The reason I cannot provide assets publicly is because it violates **Copyright Laws**. Pokémon and its trademarks are the **Intellectual Property (IP)** of **Nintendo and The Pokémon Company**. If this project distributed assets publicly, it would receive a **DMCA takedown**. By leaving assets out of the repository, the project remains completely legal.

## 🖼️ Credits
* **@mobraxton5-ux** for making the playground.
* **maierfelix** for writing some of the core server logic.
* **OpenStreetMap** for POIs and mapping data.

---
**This project is licensed under the GNU General Public License v3.0 (GPL-3.0) See LICENSE file for details**<br>
*Note: THIS SOFTWARE IS LICENSED UNDER THE GNU General Public License v3.0. IF YOU MODIFY, FORK, OR BUILD UPON THIS CODE, YOU ARE STRICTLY REQUIRED TO PUBLISH YOUR ENTIRE PROJECT AS OPEN SOURCE UNDER THE EXACT SAME LICENSE. YOU CANNOT KEEP YOUR CHANGES PRIVATE OR CLOSED-SOURCE.*<br>
**VIOLATING THIS LICENSE BY MAKING YOUR FORK CLOSED-SOURCE WILL RESULT IN IMMEDIATE REVOCATION OF YOUR RIGHTS TO USE THE CODE, POTENTIAL LEGAL ACTION FOR COPYRIGHT INFRINGEMENT, AND MANDATORY INJUNCTIONS TO FORCE THE PUBLIC RELEASE OF YOUR ENTIRE PROJECT.**
