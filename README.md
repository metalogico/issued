# Issued

**Your personal comic library server**

Host your digital comics (CBZ/CBR files) on your home server and read them on any device. Issued automatically organizes your collection and makes it available through mobile apps like Panels, Chunky, or a built-in web reader.

## What You Get

- 📚 **Keep your folder structure** – No need to reorganize your comics
- 🔄 **Automatic updates** – New comics are detected and added automatically
- 🖼️ **Thumbnail previews** – See cover images before opening
- 📱 **Read anywhere** – Use your favorite comic reader app (Panels, Chunky, etc.)
- 🌐 **Web reader** – Read in your browser without installing anything (on mobile too!)
- ⚡ **Easy setup** – One command to get started

## Server started 
<img width="553" height="207" alt="image" src="https://github.com/user-attachments/assets/fd404a7e-01e3-4000-8ae9-fbd996b79ae9" />

## Collection view
<img width="1157" height="999" alt="image" src="https://github.com/user-attachments/assets/167c9ca4-52dd-41a2-87d7-5b63ba35da15" />

## Web and Mobile reader
<img width="1054" height="993" alt="image" src="https://github.com/user-attachments/assets/17a2a55f-3191-4927-9ace-12b09a8f11cc" />

## Edit metadata (uses ComicInfo.xml if available)
<img width="1060" height="990" alt="image" src="https://github.com/user-attachments/assets/1712caa9-bf4e-4c5f-a981-a334697c1edc" />

## Continue reading and Last Added
<img width="1108" height="860" alt="image" src="https://github.com/user-attachments/assets/0fabad5a-2153-4028-8300-d697266bb888" />


## Before You Start

> **Docker users:** skip this section — the Docker image includes everything you need.

**For CBR files only** (skip if you only have CBZ):

Install `unrar` on your computer:
- **macOS**: `brew install unrar`
- **Linux**: `sudo apt install unrar`
- **Windows**: Download from [rarlab.com](https://www.rarlab.com/rar_add.htm)

> **Note:** CBZ files work without any extra software. CBR files need `unrar` to extract.

## Installation

### Option 1: Docker (Recommended)

**Best for:** Running on a home server or NAS. Everything is pre-configured, including `unrar`.

**Step 1:** Create a `docker-compose.yml` file anywhere on your server:

```yaml
services:
  issued:
    image: ghcr.io/metalogico/issued:latest
    restart: unless-stopped
    ports:
      - "8181:8181"
    volumes:
      - /path/to/your/comics:/comics:ro   # ← Change this path
      - issued_data:/app/data

volumes:
  issued_data:
```

Change `/path/to/your/comics` to your comics folder:
```yaml
- /home/user/Comics:/comics:ro     # Linux
- /Users/john/Comics:/comics:ro    # macOS
- C:/Comics:/comics:ro             # Windows
```

**Step 2:** Start the server
```bash
docker compose up -d
```

**Done!** Your comics are now available at:
- 📱 **Mobile apps**: `http://YOUR-SERVER-IP:8181/opds/`
- 🌐 **Web reader**: `http://YOUR-SERVER-IP:8181/reader/`

> Replace `YOUR-SERVER-IP` with your computer's IP address (e.g., `192.168.1.100`)

**Alternative: `docker run`**
```bash
docker run -d --name issued \
  --restart unless-stopped \
  -p 8181:8181 \
  -v /path/to/your/comics:/comics:ro \
  -v issued_data:/app/data \
  ghcr.io/metalogico/issued:latest
```

**Alternative: `docker create`** (create now, start later)
```bash
docker create \
  --name=issued \
  --user 1000:1000 \
  -p 8181:8181 \
  --mount type=bind,source=/path/to/your/comics,target=/comics,readonly \
  --mount type=bind,source=/path/to/data,target=/app/data \
  --restart unless-stopped \
  ghcr.io/metalogico/issued:latest
```
Then start it:
```bash
docker start issued
```

The image is also available on Docker Hub as `metalogico/issued`.

---

### Option 2: Standalone Executable

**Best for:** Quick setup on your personal computer.

**Step 1:** Download for your system

Get the latest release from [GitHub Releases](https://github.com/metalogico/issued/releases):
- **macOS**: `issued-macos`
- **Linux**: `issued-linux`  
- **Windows**: `issued.exe`

**Step 2:** Make it executable (macOS/Linux only)

```bash
chmod +x issued

# macOS only: If blocked by security
xattr -d com.apple.quarantine issued
```

**Step 3:** Initialize your library

```bash
# Replace with your actual comics folder path
./issued init --library /path/to/your/comics
```

Examples:
```bash
./issued init --library ~/Comics              # macOS/Linux
./issued init --library C:\Users\You\Comics   # Windows
```

**Step 4:** Scan your comics

```bash
./issued scan
```

This will:
- Find all CBZ/CBR files
- Create thumbnails
- Build the library database

**Step 5:** Start the server

```bash
./issued serve
```

**Done!** Your comics are now available at:
- 📱 **Mobile apps**: `http://YOUR-COMPUTER-IP:8181/opds/`
- 🌐 **Web reader**: `http://YOUR-COMPUTER-IP:8181/reader/`

> **Tip:** Keep the terminal window open while the server runs. New comics will be detected automatically.

---

## Using Your Comic Library

### On Mobile Apps

**Popular apps that work with Issued:**
- **Panels** (iOS/Android) - Best overall experience
- **Chunky Reader** (iOS) - Great for iPad
- **KyBook** (iOS) - Feature-rich
- **Moon+ Reader** (Android) - Highly customizable

**How to connect:**

1. Open your comic reader app
2. Add a new OPDS catalog
3. Enter: `http://YOUR-IP:8181/opds/`
4. Browse and download comics!

> **Finding your IP:** 
> - macOS/Linux: Run `ifconfig` or `ip addr`
> - Windows: Run `ipconfig`
> - Look for something like `192.168.1.100`

### In Your Browser

Just open: `http://localhost:8181/reader/`

**Optional:** Add password protection by editing `config.ini`:
```ini
[reader]
user = yourname
password = yourpassword
```

## Common Tasks

### Add new comics

Just copy them to your comics folder! If the server is running, they'll be detected automatically.

Or manually scan:
```bash
./issued scan
```

### Rescan everything

```bash
./issued scan --force
```

### Check library stats

```bash
./issued stats
```

### Regenerate all thumbnails

```bash
./issued thumbnails --regenerate
```

### Change settings

Edit `config.ini` in the same folder as the executable:
- Change port: `[server]` → `port = 8080`
- Add password: `[reader]` → `user = name`, `password = pass`
- Adjust thumbnails: `[thumbnails]` → `width`, `height`, `quality`

## Advanced Configuration

Edit `config.ini` for more options:

```ini
[library]
path = /path/to/comics    # Your comics folder
name = My Comics          # Library name shown in apps

[server]
host = 0.0.0.0           # Listen on all network interfaces
port = 8181              # Change if port is already in use

[thumbnails]
width = 300              # Thumbnail width in pixels
height = 450             # Thumbnail height in pixels
quality = 85             # JPEG quality (1-100)
format = jpeg            # jpeg or webp

[monitoring]
enabled = true           # Auto-detect new comics
debounce_seconds = 2     # Wait time before processing changes

[reader]
user =                   # Leave empty for no password
password =               # Leave empty for no password
```

## Troubleshooting

### Comics not showing up

1. **Check the scan worked:**
   ```bash
   ./issued stats
   ```
   Should show your comic count.

2. **Try a forced rescan:**
   ```bash
   ./issued scan --force
   ```

### Can't connect from mobile app

1. **Use your computer's IP address**, not `localhost`
   - Find it: `ifconfig` (Mac/Linux) or `ipconfig` (Windows)
   - Example: `http://192.168.1.100:8181/opds/`

2. **Check firewall:**
   - Make sure port 8181 is allowed
   - macOS: System Settings → Network → Firewall
   - Windows: Windows Defender Firewall → Allow an app

3. **Make sure both devices are on the same network**
   - Computer and phone/tablet must be on the same WiFi

### CBR files won't open

**Install unrar:**
- macOS: `brew install unrar`
- Linux: `sudo apt install unrar`
- Windows: Download from [rarlab.com](https://www.rarlab.com/rar_add.htm)

Then restart the server.

### macOS says "cannot be opened"

```bash
xattr -d com.apple.quarantine issued
```

### Port 8181 already in use

Edit `config.ini` and change the port:
```ini
[server]
port = 8080
```

Then use `http://YOUR-IP:8080/opds/` instead.

### Server stops when I close the terminal

**Docker:** It runs in the background automatically.

**Executable:** Run in the background:
```bash
# macOS/Linux
nohup ./issued serve &

# Or use screen/tmux
screen -S issued
./issued serve
# Press Ctrl+A then D to detach
```

## Why is it Violet / Purple?
This project uses the violet accent color just because my baby daughter is called Violet <3

---

## Getting Help

If you're stuck:
1. Check the [Issues](https://github.com/metalogico/issued/issues) page
2. Open a new issue with:
   - Your OS (macOS/Linux/Windows)
   - How you installed (Docker/executable)
   - What you tried
   - Error messages (if any)

---

## License

MIT. See [LICENSE](LICENSE) for details.