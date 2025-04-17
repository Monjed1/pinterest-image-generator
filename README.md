# Pinterest Image Generator

A Flask application that generates Pinterest-style images with customizable text and branding.

## Features

- Generates Pinterest-style images using Runware API
- Multiple style options (1-5)
- Custom title and branding text
- REST API for integration with n8n or other automation tools

## API Usage

POST to \/generate-image\ with JSON body:

\\\json
{
  "image_prompt": "beautiful landscape with mountains",
  "title": "Your Catchy Title Here",
  "BrandingURL": "yourdomain.com",
  "Style": "style1"
}
\\\

## Setup

1. Install dependencies: \pip install -r requirements.txt\
2. Set environment variables: \RUNWARE_API_KEY=your_key\
3. Run the app: \python app.py\

## Deployment

See deployment instructions in the documentation.
