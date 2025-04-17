# Pinterest Image Generator

A Flask-based web service that generates Pinterest-optimized images using the Runware AI API.

## Features

- Generate AI images using Runware API
- Apply beautiful Pinterest-style templates with titles
- Multiple design styles available
- Production-ready with robust error handling

## Setup

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file with your Runware API key:
   ```
   RUNWARE_API_KEY=your_api_key_here
   ```
4. Run the application:
   ```
   python app.py
   ```

## VPS Deployment Guide

### 1. Basic Setup

1. Clone this repository on your VPS
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and set your Runware API key

### 2. Setting Up as a Service

#### Using Systemd (recommended for Ubuntu/Debian)

1. Create a systemd service file:
   ```
   sudo nano /etc/systemd/system/pinterest-generator.service
   ```

2. Add the following content (adjust paths as needed):
   ```
   [Unit]
   Description=Pinterest Image Generator
   After=network.target

   [Service]
   User=your_user
   WorkingDirectory=/path/to/your/app
   ExecStart=/path/to/your/venv/bin/python app.py
   Restart=always
   Environment=FLASK_DEBUG=false
   Environment=PORT=5000

   [Install]
   WantedBy=multi-user.target
   ```

3. Start and enable the service:
   ```
   sudo systemctl daemon-reload
   sudo systemctl start pinterest-generator
   sudo systemctl enable pinterest-generator
   ```

### 3. Configuring Nginx as a Reverse Proxy

1. Install Nginx if not already installed:
   ```
   sudo apt update
   sudo apt install nginx
   ```

2. Create a new Nginx site configuration:
   ```
   sudo nano /etc/nginx/sites-available/pinterest-generator
   ```

3. Add the following configuration (adjust as needed):
   ```
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://localhost:5000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       # Configure static file serving (important!)
       location /static/ {
           # Option 1: Let Nginx serve static files directly
           alias /path/to/your/app/static/;
           
           # Option 2: Or pass to Flask (slower but simpler)
           # proxy_pass http://localhost:5000;
       }
   }
   ```

4. Enable the site and restart Nginx:
   ```
   sudo ln -s /etc/nginx/sites-available/pinterest-generator /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

5. Update `.env` file with proxy settings:
   ```
   PROXY_PATH=https://your-domain.com
   ```

### 4. File Permissions

Ensure your application has proper permissions to write to the static directory:

```
sudo chown -R your_user:your_user /path/to/your/app/static
sudo chmod -R 755 /path/to/your/app/static
```

### 5. Troubleshooting

If images aren't being served:

1. Check application logs for errors:
   ```
   sudo journalctl -u pinterest-generator.service -f
   ```

2. Verify the static directory exists and has proper permissions
   ```
   ls -la /path/to/your/app/static
   ```

3. Check Nginx error logs:
   ```
   sudo tail -f /var/log/nginx/error.log
   ```

4. Ensure your firewall allows HTTP/HTTPS traffic:
   ```
   sudo ufw allow 'Nginx Full'
   ```

5. Try the alternate temporary directory solution by setting this environment variable:
   ```
   FLASK_USE_TEMP_DIR=true
   ```

## API Usage

Generate an image by sending a POST request to `/generate-image` with the following JSON payload:

```json
{
  "image_prompt": "Your AI image prompt",
  "title": "Title to display on the image",
  "BrandingURL": "Optional branding URL",
  "Style": "style1"  // style1, style2, style3, style4, or style5
}
```

The API will return a JSON response with the URL to the generated image:

```json
{
  "image_url": "http://your-server/static/generated_image.png",
  "status": "success"
}
```
