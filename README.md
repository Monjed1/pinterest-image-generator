# Pinterest Image Generator

A Flask-based web service that generates Pinterest-optimized images with beautiful text overlays and styling. Integrates with the Runware AI API for image generation.

## Features

- Generate AI images using Runware API integration
- Five distinct Pinterest-optimized design styles:
  - **Style 1**: Gold title text in a transparent black box with rounded corners, "Read More" button, and branding URL in a black footer bar
  - **Style 2**: Elegant golden text with enhanced shadow effect, cream-colored "Read More" button, and branding URL in a dark footer
  - **Style 3**: Clean white text on black bars with perfectly centered branding URL and "Read More" button above the footer
  - **Style 4**: Gold-colored text in a dark bottom rectangle with golden box containing branding URL in black text
  - **Style 5**: White text on dark curved background with branding URL in a white box with black text
- Dynamic text sizing that automatically adjusts for longer titles
- Perfect vertical and horizontal centering of text elements
- Customizable branding URL in various style-specific formats
- Rounded corners for Pinterest-friendly presentation
- Modern "Read More" buttons with style-specific designs
- Production-ready with robust error handling

## Visual Styling Details

### Style 1
- Black transparent box for title with gold text (#d7bd45)
- Light gray "Read More" button positioned at bottom
- Branding URL in a black footer bar with custom font
- Rounded corner image format

### Style 2
- Golden text with enhanced shadow for readability
- Dark overlay for improved text visibility
- Cream-colored "Read More" button
- Branding URL in dark footer with light gold text
- Shadow effect on the entire image

### Style 3
- Black bars at top and bottom
- Clean white title text in the top bar
- "Read More" button positioned above the bottom bar
- Branding URL centered in the bottom bar

### Style 4
- Dark rectangle at bottom containing title
- Golden title text with elegant font
- Branding URL in a golden box with black text
- Dynamic font sizing for long titles

### Style 5
- Dark curved section at the bottom
- White bold text with shadow
- Branding URL in a white box with black text
- Perfect optical centering of text elements

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

## Local Development

For local development, you can run the server with:

```
python app.py
```

The server will start on port 5000 by default. You can access it at http://localhost:5000.

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

### Style Selection

Choose from five available styles:
- `style1`: Gold text in black transparent box with footer
- `style2`: Golden text with shadow effects and footer
- `style3`: White text on black bars (top and bottom)
- `style4`: Gold text in dark rectangle with golden branding box
- `style5`: White text on curved dark background with white branding box

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `image_prompt` | string | Yes | Prompt for AI image generation |
| `title` | string | Yes | Title text to display on the image |
| `BrandingURL` | string | No | URL or text to display in branding area |
| `Style` | string | No | Image style (style1-5, defaults to style1) |

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

### 5. SSL Configuration with Certbot

For HTTPS support, install Certbot and obtain SSL certificates:

1. Install Certbot:
   ```
   sudo apt install certbot python3-certbot-nginx
   ```

2. Obtain a certificate:
   ```
   sudo certbot --nginx -d your-domain.com
   ```

3. Follow the prompts to complete the SSL setup

### 6. Troubleshooting

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

## Docker Deployment

### 1. Build the Docker image

```
docker build -t pinterest-generator .
```

### 2. Run the container

```
docker run -d -p 5000:5000 --name pinterest-app --env-file .env pinterest-generator
```

### 3. Docker Compose (alternative)

Create a `docker-compose.yml` file:

```yaml
version: '3'
services:
  pinterest-app:
    build: .
    ports:
      - "5000:5000"
    env_file:
      - .env
    volumes:
      - ./static:/app/static
    restart: always
```

Run with:
```
docker-compose up -d
```

## Font Customization

The application uses several bundled fonts with fallbacks. You can customize the fonts by:

1. Adding your own font files to the `font/` directory
2. Modifying the font preferences arrays in the code:
   - `main_font_preferences` for titles
   - `branding_font_preferences` for branding URL
   - Style-specific font preferences (style3_font_preferences, etc.)

## Performance Optimization

For high-traffic deployments:

1. Configure a CDN for serving static images
2. Use Redis for caching frequent image generation requests
3. Implement a queue system for processing image requests

## Credits

- Uses [Runware AI API](https://runware.ai/) for image generation
- Built with Flask, Pillow, and other open-source libraries
