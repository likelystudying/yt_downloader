# yt-dlp GUI Manager

A user-friendly graphical interface for downloading videos and audio from YouTube using yt-dlp. This tool simplifies the process of downloading media with an intuitive GUI, automatic dependency management, and organized file storage.

## ✨ Features

- **Easy-to-use GUI**: Simple interface for downloading videos and audio
- **Automatic Setup**: Installs and updates yt-dlp automatically
- **FFmpeg Integration**: Downloads and configures FFmpeg for media conversion
- **Dual Format Support**:
  - Video: Downloads in MP4 format
  - Audio: Extracts and converts to MP3
- **Visual Feedback**: Real-time download progress and logging
- **Organized Storage**: Automatically creates and manages download folders
- **Three Versions Available**:
  - **PowerShell** (Windows-only): Native Windows GUI
  - **Python** (Cross-platform): Works on Windows, macOS, and Linux
  - **Mac + Chrome extension**: download from Chrome's toolbar or right-click menu, no Terminal needed.
    See [mac/README.md](mac/README.md).

## 🚀 Getting Started

### PowerShell Version (Windows)

#### Prerequisites
- Windows 10/11
- PowerShell 5.1 or higher (pre-installed on Windows)
- Python 3.x installed and in PATH
- Internet connection

#### Installation
1. Clone this repository:
   ```powershell
   git clone https://github.com/yourusername/yt-dlp-gui-manager.git
   cd yt-dlp-gui-manager
   ```

2. Run the application:
   ```powershell
   .\yt-dlp-gui.ps1
   ```

### Python Version (Cross-Platform)

#### Prerequisites
- Python 3.7 or higher
- tkinter (usually comes with Python)
- Internet connection

#### Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/yt-dlp-gui-manager.git
   cd yt-dlp-gui-manager
   ```

2. Run the application:
   ```bash
   python yt-dlp-gui.py
   ```
   
   Or on macOS/Linux:
   ```bash
   python3 yt-dlp-gui.py
   ```

## 📖 Usage

1. **First Run Setup**:
   - Click "Install yt-dlp" to install/update yt-dlp
   - Click "Install FFmpeg" to download and configure FFmpeg

2. **Download Video**:
   - Paste a YouTube URL in the text field
   - Click "Download Video (MP4)"
   - Videos are saved to: `V_A_downloads/videos/`

3. **Download Audio**:
   - Paste a YouTube URL in the text field
   - Click "Download Audio (MP3)"
   - Audio files are saved to: `V_A_downloads/audios/`

4. **Monitor Progress**:
   - View real-time download progress and logs in the output window

## 📁 Project Structure

```
.
├── yt-dlp-gui.ps1          # PowerShell GUI version (Windows)
├── yt-dlp-gui.py           # Python GUI version (Cross-platform)
├── install-yt-dl.cmd       # Windows batch installer
├── run-yt-dl.cmd           # Windows batch runner
├── mi_yt_dlp/              # yt-dlp and FFmpeg installation folder
└── V_A_downloads/          # Downloads folder
    ├── videos/             # Downloaded videos (MP4)
    └── audios/             # Downloaded audio (MP3)
```

## 🛠️ Dependencies

This application uses the following open-source tools:

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)**: A feature-rich command-line audio/video downloader
- **[FFmpeg](https://ffmpeg.org/)**: A complete, cross-platform solution for recording, converting, and streaming audio and video

Both dependencies are automatically downloaded and configured by the application.

## ⚠️ Important Notes

- Respect copyright laws and YouTube's Terms of Service
- Only download content you have the right to download
- This tool is for personal use only
- Some videos may be restricted based on geographic location or copyright

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### Third-Party Licenses
- **yt-dlp**: Unlicense (Public Domain)
- **FFmpeg**: LGPL 2.1+ / GPL 2+ (depending on build configuration)

## 👤 Author

**Gregorio Parra**
- Assistant: Claude Sonnet 4.5

## 🙏 Acknowledgments

- Thanks to the yt-dlp development team
- Thanks to the FFmpeg project
- Built with assistance from Claude AI

## 📞 Support

If you encounter any issues or have questions, please open an issue on GitHub.

---

**Disclaimer**: This tool is provided as-is for educational and personal use. The authors are not responsible for any misuse of this software.
