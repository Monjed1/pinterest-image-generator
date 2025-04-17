# Pinterest Image Generator API

A Flask REST API that generates Pinterest-style images with custom text overlays.

## Features

- Accepts an image URL and title text
- Resizes the image to Pinterest standard dimensions (1000x1500px)
- Upscales low-quality images using LANCZOS filter
- Adds a blurred background behind text for better readability
- Auto-scales font size based on text length
- Returns a downloadable PNG image

## Installation

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Running the API

Start the API server:

```bash
python app.py
```

The API will be available at `http://localhost:5000`

## API Usage

### Generate Pinterest Image

**Endpoint:** POST `/generate-pin`

**Request Body (JSON):**
```json
{
  "bg_url": "https://example.com/image.jpg",
  "title": "Your text overlay here"
}
```

**Response:**
- A downloadable PNG image file

## Error Handling

The API handles various errors:
- Invalid JSON data
- Missing required parameters
- Failed image downloads
- Image processing errors

## CORS Support

This API supports Cross-Origin Resource Sharing (CORS), allowing it to be called from any origin. 


rva38vVxXnEqnQ2PVZuzPtTCi6sk0pY2