from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from PIL import Image, ImageFilter, ImageDraw, ImageFont, UnidentifiedImageError, ImageEnhance
import requests
import io
import os
import tempfile
import mimetypes
import logging
import json
import time
import asyncio
from io import BytesIO
import base64
from werkzeug.exceptions import BadRequest

# For Runware SDK
import uuid
import aiohttp
from dotenv import load_dotenv
import math
import sys
import pathlib

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables if any
load_dotenv()
print(f"load_dotenv() executed.") # See if this line runs
print(f"Value for RUNWARE_API_KEY from os.getenv: {os.getenv('RUNWARE_API_KEY')}")

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Runware SDK client implementation for Flask (non-async wrapper)
class RunwareClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.runware.ai/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def generate_image(self, prompt, width=1152, height=2048, model="rundiffusion:130@100"):
        """Generate an image using Runware API with blocking implementation for Flask"""
        logger.info(f"Generating image with prompt: {prompt}")
        
        # Create a unique taskUUID for this request
        task_uuid = str(uuid.uuid4())
        logger.info(f"Generated taskUUID: {task_uuid}")
        
        # Create the task payload according to the API documentation
        # This must be in an array format even for a single task
        payload = [{
            "taskType": "imageInference",
            "taskUUID": task_uuid,
            "positivePrompt": prompt,
            "negativePrompt": "low quality, bad anatomy, distorted, blurry",
            "height": height,
            "width": width,
            "model": model,
            "steps": 35,
            "CFGScale": 7.0,
            "outputType": ["URL"],
            "outputFormat": "JPEG",
            "numberResults": 1,
            "includeCost": True
        }]
        
        try:
            # Log what we're about to send
            logger.info(f"Sending task creation request to Runware API")
            logger.info(f"Request payload: {json.dumps(payload)}")
            
            # Create the task
            response = requests.post(
                f"{self.base_url}/tasks",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            # Log response
            logger.info(f"Task creation response status: {response.status_code}")
            logger.info(f"Response content: {response.text}")
            
            # Check for API-specific errors
            if response.status_code == 401 or response.status_code == 403:
                raise Exception(f"Authentication failed. Your API key may be invalid. Status: {response.status_code}")
            elif response.status_code != 200:
                error_text = response.text
                try:
                    error_json = response.json()
                    if "errors" in error_json and error_json["errors"]:
                        error_details = []
                        for error in error_json["errors"]:
                            error_msg = f"{error.get('code', 'Unknown')}: {error.get('message', 'No message')}"
                            error_details.append(error_msg)
                        error_text = ", ".join(error_details)
                except:
                    pass
                raise Exception(f"Failed to create task: {error_text}")
            
            # Parse the response
            response_data = response.json()
            logger.info(f"Parsed response data: {json.dumps(response_data)}")
            
            # Check if there's data in the response
            if "data" not in response_data or not response_data["data"]:
                raise Exception("Response doesn't contain any data")
            
            # Extract image URL from response
            task_result = response_data["data"][0]  # The first (and likely only) result
            
            if "imageURL" in task_result:
                image_url = task_result["imageURL"]
                logger.info(f"Image URL from response: {image_url}")
                
                # Download the image
                logger.info(f"Downloading image from URL: {image_url}")
                img_response = requests.get(image_url, timeout=30)
                
                if img_response.status_code != 200:
                    raise Exception(f"Failed to download generated image: {img_response.status_code}")
                
                return img_response.content
            else:
                # No image URL - we might need to poll for completion
                logger.info("No immediate image URL - proceeding to poll for task completion")
                return self._poll_for_completion(task_uuid)
            
        except Exception as e:
            logger.exception(f"Error in generate_image: {str(e)}")
            raise
    
    def _poll_for_completion(self, task_uuid):
        """Poll for task completion and return the image data"""
        logger.info(f"Polling for completion of task: {task_uuid}")
        
        max_polls = 30
        for i in range(max_polls):
            logger.info(f"Polling attempt {i+1}/{max_polls}")
            
            try:
                # Wait before polling
                if i > 0:
                    time.sleep(2)
                
                # Get task status
                response = requests.get(
                    f"{self.base_url}/tasks/{task_uuid}",
                    headers=self.headers,
                    timeout=15
                )
                
                logger.info(f"Poll response status: {response.status_code}")
                
                if response.status_code != 200:
                    logger.warning(f"Failed to get task status: {response.text}")
                    continue
                
                # Parse response
                response_data = response.json()
                
                if "data" not in response_data:
                    logger.warning(f"Unexpected response format: {json.dumps(response_data)}")
                    continue
                
                task_data = response_data["data"]
                
                # Check task status
                if task_data.get("status") == "completed":
                    logger.info("Task completed successfully")
                    
                    # Get the image URL
                    if "imageURL" in task_data:
                        image_url = task_data["imageURL"]
                    elif "output" in task_data and "images" in task_data["output"] and task_data["output"]["images"]:
                        image_url = task_data["output"]["images"][0].get("url")
                    else:
                        raise Exception("No image URL found in completed task")
                    
                    logger.info(f"Downloading image from URL: {image_url}")
                    
                    # Download the image
                    img_response = requests.get(image_url, timeout=30)
                    
                    if img_response.status_code != 200:
                        raise Exception(f"Failed to download generated image: {img_response.status_code}")
                    
                    return img_response.content
                    
                elif task_data.get("status") == "failed":
                    error = task_data.get("error", "Unknown error")
                    raise Exception(f"Task failed: {error}")
                    
                else:
                    logger.info(f"Task status: {task_data.get('status', 'unknown')}")
            
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error during polling: {str(e)}")
                # Continue polling despite errors
            except Exception as e:
                if "Task failed" in str(e) or "No image URL found" in str(e):
                    raise
                logger.error(f"Error during polling: {str(e)}")
        
        raise Exception(f"Timed out waiting for task completion after {max_polls} attempts")

# Initialize Runware client using environment variable
runware_api_key_from_env = os.getenv("RUNWARE_API_KEY")
if not runware_api_key_from_env:
    logger.error("RUNWARE_API_KEY environment variable not set. RunwareClient will not function.")
    # Optionally, you could raise an error here or disable related endpoints
    runware_client = None # Indicate client is not available
else:
    runware_client = RunwareClient(api_key=runware_api_key_from_env)

# --- Font Loading Helper ---
def load_bundled_font(font_names, size):
    """Attempts to load a font from the 'font/' directory in the given order.

    Args:
        font_names (list): A list of font filenames (e.g., ['font1.ttf', 'font2.otf']).
        size (int): The desired font size.

    Returns:
        ImageFont: A Pillow font object, falling back to default if none are found.
    """
    base_path = 'font/'
    for font_name in font_names:
        try:
            font_path = os.path.join(base_path, font_name)
            if os.path.exists(font_path):
                logger.info(f"Loading font: {font_path} at size {size}")
                return ImageFont.truetype(font_path, size)
            else:
                 logger.warning(f"Bundled font not found: {font_path}")
        except IOError as e:
            logger.warning(f"Could not load font {font_name}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error loading font {font_name}: {e}")

    logger.warning(f"No bundled fonts found from list: {font_names}. Trying system fallbacks.")

    # --- Try specific common system fonts before generic default ---
    # Pillow's ImageFont.truetype can often find system fonts by name
    common_fallbacks = ['arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf', 'Verdana.ttf'] # Added Verdana
    for fallback_name in common_fallbacks:
        try:
            logger.info(f"Attempting system fallback: {fallback_name} at size {size}")
            # Try loading directly by name, letting Pillow search
            return ImageFont.truetype(fallback_name, size)
        except IOError:
            # This specific font name wasn't found or readable by Pillow
            logger.warning(f"System fallback font '{fallback_name}' not found or loadable by Pillow.")
        except Exception as e:
             # Catch other potential errors during font loading
             logger.error(f"Unexpected error loading system fallback {fallback_name}: {e}")

    # --- Fallback to Pillow's default --- 
    logger.error(f"All bundled and specific system fallback fonts failed. Loading Pillow default font (size may be incorrect on Pillow < 10).)")
    try:
        # Pillow >= 10 default font behavior
        return ImageFont.load_default(size=size) 
    except TypeError:
        # Older Pillow versions might not accept size for load_default
         logger.warning("Pillow version might be < 10.0. Trying load_default() without size (will be small).")
         return ImageFont.load_default()
    except Exception as e:
        # Catch any other potential error with load_default itself
        logger.error(f"Error loading Pillow default font: {e}")
        # If font is absolutely critical, could raise an Exception here
        # For now, returning None might allow processing to continue if possible,
        # but text drawing will likely fail later.
        return None 

@app.route('/generate-image', methods=['POST'])
def generate_image():
    # Add check for client availability
    if runware_client is None:
        return jsonify({"error": "Runware client is not configured due to missing API key."}), 503 # 503 Service Unavailable

    # Parse request
    data = request.json
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    
    # Get parameters with the requested names
    image_prompt = data.get('image_prompt')
    title = data.get('title')
    branding_url = data.get('BrandingURL', '')  # Optional parameter for branding/URL footer
    style = data.get('Style', 'style1')  # Default to style1 if not provided
    
    # Validate required fields
    if not image_prompt:
        return jsonify({"error": "Missing image_prompt parameter"}), 400
    if not title:
        return jsonify({"error": "Missing title parameter"}), 400
    
    try:
        # Generate image using Runware API
        try:
            logger.info(f"Generating AI image with Runware API with prompt: {image_prompt}")
            # Use the correct default size matching the generate_image definition
            image_data = runware_client.generate_image(prompt=image_prompt, width=1024, height=1024)
            logger.info("Runware AI image generation successful")
        except Exception as e:
            # If Runware fails, log the error and return it
            logger.exception(f"Error generating AI image with Runware API: {str(e)}")
            return jsonify({"error": f"Failed to generate image using Runware API: {str(e)}"}), 500
        
        # Process the image (reusing existing code from generate_from_prompt)
        image_buffer = io.BytesIO(image_data)
        img = Image.open(image_buffer)
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize to Pinterest standard if needed
        target_size = (1000, 1500)
        if img.size != target_size:
            img = img.resize(target_size, Image.LANCZOS)
            
        # Apply a subtle color enhancement
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.1)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(1.15)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.05)
        
        # Define font preferences early, before any potential usage
        main_font_preferences = [
            'PoetsenOne-Regular.ttf', 'LeagueSpartan-Bold.ttf', 'Montserrat-Bold.ttf',
            'Lato-Bold.ttf', 'OpenSans-Bold.ttf', 'Poppins-Bold.ttf',
            'arialbd.ttf', 'Arial-Bold.ttf'
        ]
        branding_font_preferences = [
            'DejaVuSans-Light.ttf', 'Calibril.ttf', 'seguisli.ttf',
            'LeagueSpartan-Light.ttf', 'Montserrat-Light.ttf', 'Lato-Light.ttf',
            'OpenSans-Light.ttf', 'Poppins-Light.ttf', 'arial.ttf'
        ]
        
        # Style 3 specific font preferences
        style3_font_preferences = [
            'Nunito-ExtraBold.ttf', 'Montserrat-ExtraBold.ttf', 'OpenSans-ExtraBold.ttf',
            'Lato-Bold.ttf', 'Poppins-Bold.ttf'
        ]
        
        # Style 4 specific font preferences
        style4_font_preferences = [
            'Vidaloka-Regular.ttf', 'Times New Roman Bold.ttf', 'Georgia Bold.ttf',
            'PlayfairDisplay-Bold.ttf', 'Merriweather-Bold.ttf'
        ]
        
        # Style 5 specific font preferences - using LeagueSpartan-Bold for title as specified
        style5_font_preferences = [
            'LeagueSpartan-Bold.ttf', 'Montserrat-Bold.ttf', 'OpenSans-Bold.ttf',
            'Lato-Bold.ttf', 'Arial-Bold.ttf', 'arialbd.ttf'
        ]
        
        # Base font size definition
        base_font_size = 80
        
        # Define the text wrapping function early
        def wrap_text(text, font_obj, max_w):
            words = text.split()
            lines = []
            current_line = []
            temp_draw = ImageDraw.Draw(Image.new('RGB', (1,1))) # Temp draw for textlength
            for word in words:
                test_line = ' '.join(current_line + [word])
                test_width = temp_draw.textlength(test_line, font=font_obj)
                if test_width <= max_w:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
            if current_line:
                lines.append(' '.join(current_line))
            return lines
        
        # Apply modern, low-contrast background effect 
        bg_effect = img.copy()
        enhancer = ImageEnhance.Contrast(bg_effect)
        bg_effect = enhancer.enhance(0.85)
        tint_overlay = Image.new('RGBA', target_size, (66, 66, 77, 25))
        bg_effect = Image.alpha_composite(bg_effect.convert('RGBA'), tint_overlay)
        gradient_overlay = Image.new('RGBA', target_size, (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient_overlay)
        for y in range(target_size[1]):
            progress = y / target_size[1]
            alpha = int(15 * progress) if progress < 0.5 else int(15 * (1 + (progress - 0.5)))
            gradient_draw.line([(0, y), (target_size[0], y)], fill=(0, 0, 0, alpha))
        bg_effect = Image.alpha_composite(bg_effect, gradient_overlay).convert('RGB')
        img = bg_effect
        
        # Define helper function for rounded corners (used by multiple styles)
        def add_rounded_corners(image, radius=40):
            image = image.convert("RGBA")
            mask = Image.new('L', image.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), image.size], radius=radius, fill=255)
            result = Image.new('RGBA', image.size, (0, 0, 0, 0))
            result.paste(image, (0, 0), mask)
            return result
        
        # Additional background treatment for Style 2 to improve text readability
        if style == 'style2':
            # Convert to RGBA for overlay
            img = img.convert('RGBA')
            
            # Create a semi-transparent overlay
            overlay = Image.new('RGBA', target_size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            
            # Add a central area with more transparency for focal point
            center_x, center_y = target_size[0] // 2, target_size[1] // 2
            max_radius = max(target_size) * 0.7
            
            # Draw radial gradient overlay
            for y in range(target_size[1]):
                for x in range(target_size[0]):
                    # Calculate distance from center (normalized)
                    distance = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5 / max_radius
                    distance = min(1.0, distance)  # Cap at 1.0
                    
                    # More opacity at edges (up to 100), less in center (min 40)
                    opacity = int(40 + 60 * distance)
                    overlay_draw.point((x, y), fill=(0, 0, 0, opacity))
            
            # Apply overlay to image
            img = Image.alpha_composite(img, overlay).convert('RGB')
            img = img.convert('RGBA')  # Convert back for further processing
        
        # Style 3 implementation - add black bars at top and bottom
        elif style == 'style3':
            # Convert to RGBA for adding bars
            img = img.convert('RGBA')
            
            # First calculate text dimensions to determine appropriate top bar height
            style3_font_scale = 1.1
            style3_font = load_bundled_font(style3_font_preferences, int(base_font_size * style3_font_scale))
            temp_font = style3_font if style3_font else font
            
            # Calculate wrapped text height
            temp_draw = ImageDraw.Draw(Image.new('RGB', (1,1)))
            max_text_width = target_size[0] - 80  # Some padding from edges
            
            # Wrap text for measurement
            temp_wrapped_lines = wrap_text(title, temp_font, max_text_width)
            
            # Calculate total text height
            line_heights_temp = []
            for line in temp_wrapped_lines:
                try:
                    bbox = temp_draw.textbbox((0,0), line, font=temp_font)
                    line_heights_temp.append(bbox[3] - bbox[1])
                except:
                    # Fallback if textbbox not available
                    line_heights_temp.append(base_font_size * style3_font_scale)
            
            # Calculate total height with spacing
            total_text_height = sum(h * 1.2 for h in line_heights_temp)
            
            # Define dimensions for the black bars - dynamic top bar
            top_padding = 50  # Padding above and below text
            top_bar_height = int(total_text_height + (top_padding * 2))  # Adjust based on text
            top_bar_height = max(170, min(320, top_bar_height))  # Min/max bounds for aesthetics
            bottom_bar_height = 180  # Bar at bottom for branding
            
            # Create new image with space for bars
            new_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
            
            # Create black bars with slight transparency for elegance
            top_bar_color = (33, 33, 35, 240)  # #212123 with transparency
            top_bar = Image.new('RGBA', (target_size[0], top_bar_height), top_bar_color)
            bottom_bar = Image.new('RGBA', (target_size[0], bottom_bar_height), top_bar_color)  # Use same color for bottom bar
            
            # Paste the main image first
            new_img.paste(img, (0, 0))
            
            # Then overlay the bars
            new_img.paste(top_bar, (0, 0), top_bar)
            new_img.paste(bottom_bar, (0, target_size[1] - bottom_bar_height), bottom_bar)
            
            # Update img and draw for further processing
            img = new_img
            
        # Style 4 implementation - Image at top, dark rectangle at bottom with title and branding
        elif style == 'style4':
            logger.debug("Applying Style 4")
            # Convert to RGBA for adding elements
            img = img.convert('RGBA')
            
            # Define dimensions for bottom rectangle
            bottom_rect_height = 450  # Bottom dark rectangle height
            logger.debug(f"Style 4: bottom_rect_height = {bottom_rect_height}")
            
            # Create new image for composition
            new_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
            
            # Create bottom dark rectangle with slight transparency
            bottom_rect_color = (30, 30, 30, 245)  # Dark gray/black with transparency
            bottom_rect = Image.new('RGBA', (target_size[0], bottom_rect_height), bottom_rect_color)
            
            # Paste the main image first
            new_img.paste(img, (0, 0))
            
            # Then overlay the bottom rectangle
            new_img.paste(bottom_rect, (0, target_size[1] - bottom_rect_height), bottom_rect)
            
            # Update img for further processing
            img = new_img
        
        # Style 5 implementation - Image at top with curved dark shape at bottom
        elif style == 'style5':
            # Convert to RGBA for adding elements
            img = img.convert('RGBA')
            
            # Define dimensions for the curved dark shape
            dark_section_height = 1300  # Height of the dark section from bottom
            image_visible_height = target_size[1] - dark_section_height  # How much of the image will be visible
            
            # Parabola parameters (matching the example)
            peak_height_ratio = 0.6  # Height of peak as fraction of dark section height
            steepness_factor = 0.3   # How quickly curve drops off from center
            
            # Create a new image for composition
            new_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
            
            # Position the image so its center is at the top portion
            # First calculate the offset needed to move the image up
            # For 1:1 original image that's 1024x1024, we need to offset to show the center
            img_width, img_height = img.size
            
            # Calculate vertical offset to position the image lower to hide the bottom portion
            # Using a negative offset to descend (move down) the image
            # This will hide more of the image behind the dark curved area
            y_offset = -150  # Negative value moves the image down
            
            # Create a mask for the curved shape
            mask = Image.new('L', target_size, 0)
            mask_draw = ImageDraw.Draw(mask)
            
            # Calculate curve positions
            curve_start_y = target_size[1] - dark_section_height
            peak_y = dark_section_height * peak_height_ratio
            center_x = target_size[0] / 2
            
            # Calculate parabola scaling factor
            a = (steepness_factor * peak_y) / (center_x**2)
            
            # First fill the entire bottom section (below where curve would end)
            mask_draw.rectangle([(0, curve_start_y + peak_y), (target_size[0], target_size[1])], fill=255)
            
            # Generate points for the parabolic curve
            curve_points = []
            # Add bottom-left corner first
            curve_points.append((0, target_size[1]))
            
            # Calculate and add all curve points
            num_points = 100  # Number of points to generate along curve
            for i in range(num_points + 1):
                x = i * target_size[0] / num_points
                # Calculate parabola: y = -a * (x - center_x)^2 + peak_y + curve_start_y
                y = -a * (x - center_x)**2 + peak_y + curve_start_y
                curve_points.append((x, y))
            
            # Add bottom-right corner
            curve_points.append((target_size[0], target_size[1]))
            
            # Draw the filled polygon
            mask_draw.polygon(curve_points, fill=255)
            
            # Create the dark section overlay with the mask
            dark_section = Image.new('RGBA', target_size, (30, 30, 35, 245))  # Dark gray/black
            dark_section.putalpha(mask)
            
            # Paste the main image with the calculated offset to center it in the top portion
            new_img.paste(img, (0, y_offset))
            
            # Then overlay the dark section using the mask
            new_img = Image.alpha_composite(new_img, dark_section)
            
            # Update img for further processing
            img = new_img
        
        # Prepare for text overlay
        draw = ImageDraw.Draw(img) # Initial draw object on base image
        
        # --- Font Loading ---
        branding_font_size = 60 # Note: subtitle font seems unused currently

        logger.info("Loading main font...")
        font = load_bundled_font(main_font_preferences, base_font_size)

        # --- Auto-scale font size / Text wrapping ---
        max_width = target_size[0] - 120 # Max width for title text
        
        # For style 2, increase the text padding from edges
        if style == 'style2':
            # Use more padding to keep text further from edges
            max_width = target_size[0] - 160
        
        # Initial wrap
        wrapped_lines = wrap_text(title, font, max_width)
        
        # Dynamically adjust font size
        while len(wrapped_lines) > 6 and base_font_size > 30:
            base_font_size -= 5
            logger.info(f"Text too long, reducing main font size to {base_font_size}")
            font = load_bundled_font(main_font_preferences, base_font_size) # Reload font
            wrapped_lines = wrap_text(title, font, max_width)
            
        # Calculate text height and position
        line_heights = []
        try:
            # Use textbbox if available (more accurate)
            line_heights = [draw.textbbox((0,0), line, font=font)[3] - draw.textbbox((0,0), line, font=font)[1] for line in wrapped_lines]
        except AttributeError:
            # Fallback for older Pillow versions or if textbbox fails
            logger.warning("draw.textbbox not available or failed, using textsize as fallback for height.")
            line_heights = [draw.textsize(line, font=font)[1] for line in wrapped_lines] # Fallback
            
        line_spacing_factor = 1.3
        total_text_height = sum(lh * line_spacing_factor for lh in line_heights) - (line_heights[0] * (line_spacing_factor - 1.2)) # Adjust first line spacing
        available_height = target_size[1]
        logger.debug(f"Calculated line heights: {line_heights}")
        logger.debug(f"Calculated total_text_height: {total_text_height}")
        
        # Adjust text position based on style
        if style == 'style2':
            # For Style 2, position text at the top of the image with proper padding
            text_y = 80  # Fixed position from top with good padding
            
            # Check if text might be too close to bottom elements
            if text_y + total_text_height > available_height - 200:
                # If text is very long and would overlap with bottom elements, adjust as needed
                text_y = max(40, available_height - 200 - total_text_height)
        elif style == 'style3':
            # For Style 3, position text in the top black bar, centered vertically
            # We need to reference the top_bar_height calculated earlier
            text_y = (top_bar_height - total_text_height) // 2  # Center text vertically in top bar
            # Ensure perfect centering by adjusting for any rounding errors
            text_y = max(20, text_y)  # Ensure minimum padding from top, but allow more centering
        elif style == 'style4':
            # For Style 4, position text in the bottom rectangle
            # Position based on available space within the bottom rectangle
            # Assuming the branding bar is at bottom, position title above it
            # bottom_rect_height = 450 # Already defined
            
            # Reserve space at bottom for branding bar (will be added later)
            branding_bar_height = 60
            branding_bar_margin = 60  # Space between branding bar and title
            
            # Calculate where to position the title - centered in remaining space
            title_area_height = bottom_rect_height - branding_bar_height - branding_bar_margin
            text_y = target_size[1] - bottom_rect_height + (title_area_height - total_text_height) // 2
            logger.debug(f"Style 4: title_area_height = {title_area_height}")
            logger.debug(f"Style 4: Calculated initial text_y = {text_y}")
            # Ensure minimum padding
            text_y = max(target_size[1] - bottom_rect_height + 40, text_y)
            logger.debug(f"Style 4: Final text_y after padding adjustment = {text_y}")
        elif style == 'style5':
            # For Style 5, position title in the curved dark section
            # We want to center it vertically in the dark section, adjusting for the curve
            dark_section_height = 550  # Must match the value from the style5 implementation
            curve_height = 100  # Must match the value from the style5 implementation
            
            # Calculate the visible area height (excluding the transition curve)
            visible_area_height = dark_section_height - curve_height
            
            # Calculate title position centered in visible area
            # Add offset to account for curved part
            curve_offset = 40  # Additional offset to move title down from curve
            text_y = target_size[1] - visible_area_height + ((visible_area_height - total_text_height) // 2) + curve_offset
            
            # Ensure title doesn't go too close to the bottom
            min_bottom_margin = 120  # Minimum space from bottom for branding URL
            if text_y + total_text_height > target_size[1] - min_bottom_margin:
                text_y = target_size[1] - min_bottom_margin - total_text_height
        else: # Style 1
            # Style 1 positioning - also moved to top
            text_y = 80  # Fixed position from top with good padding (same as Style 2)
            
            # Check if text might be too close to bottom elements
            if text_y + total_text_height > available_height - 200:
                # If text is very long and would overlap with bottom elements, adjust as needed
                text_y = max(40, available_height - 200 - total_text_height)

        # --- Text Background Box (Only for Style 1) ---
        if style == 'style1':
            padding = 35
            corner_radius = 25
            bg_color = (0, 0, 0, 140)
            shadow_color_box = (0, 0, 0, 70)
            shadow_offset_box = (5, 5)

            # Calculate text block bounding box
            max_line_width = 0
            _current_y_bbox = text_y # Use a temp var for bbox calculation y
            text_block_bbox = [target_size[0], target_size[1], 0, 0] # [min_x, min_y, max_x, max_y]
            for i, line in enumerate(wrapped_lines):
                line_width = draw.textlength(line, font=font)
                max_line_width = max(max_line_width, line_width)
                line_x = (target_size[0] - line_width) // 2
                actual_line_height = line_heights[i] * (line_spacing_factor if i > 0 else 1.2)
                text_block_bbox[0] = min(text_block_bbox[0], line_x)
                text_block_bbox[1] = min(text_block_bbox[1], _current_y_bbox)
                text_block_bbox[2] = max(text_block_bbox[2], line_x + line_width)
                text_block_bbox[3] = max(text_block_bbox[3], _current_y_bbox + actual_line_height)
                _current_y_bbox += actual_line_height

            # Calculate box dimensions
            box_left = int(text_block_bbox[0] - padding)
            box_top = int(text_block_bbox[1] - padding)
            box_right = int(text_block_bbox[2] + padding)
            box_bottom = int(text_block_bbox[3] + padding * 0.5)
            box_width = box_right - box_left
            box_height = box_bottom - box_top

            # Ensure box is within bounds
            box_left = max(0, box_left)
            box_top = max(0, box_top)
            box_right = min(target_size[0], box_right)
            box_bottom = min(target_size[1], box_bottom)
            box_width = box_right - box_left
            box_height = box_bottom - box_top

            if box_width > 0 and box_height > 0:
                # Draw box on a separate surface and composite
                box_surface = Image.new('RGBA', img.size, (0,0,0,0))
                box_draw = ImageDraw.Draw(box_surface)
                # Shadow
                shadow_rect = [(box_left + shadow_offset_box[0], box_top + shadow_offset_box[1]),
                               (box_right + shadow_offset_box[0], box_bottom + shadow_offset_box[1])]
                box_draw.rounded_rectangle(shadow_rect, radius=corner_radius, fill=shadow_color_box)
                # Main box
                main_rect = [(box_left, box_top), (box_right, box_bottom)]
                box_draw.rounded_rectangle(main_rect, radius=corner_radius, fill=bg_color)
                # Composite
                img = Image.alpha_composite(img.convert('RGBA'), box_surface) # Keep as RGBA for now
                draw = ImageDraw.Draw(img) # Re-assign draw object to the updated image

        # --- Text Drawing ---
        current_y = text_y # Reset Y position for drawing
        logger.debug(f"Starting text drawing at current_y = {current_y}")
        for i, line in enumerate(wrapped_lines):
            logger.debug(f"Drawing line {i+1}/{len(wrapped_lines)}: '{line}'")
            try:
                 # Use textlength if available (more accurate)
                 line_width = draw.textlength(line, font=font)
            except AttributeError:
                 logger.warning("draw.textlength not available, using textsize as fallback for width.")
                 line_width = draw.textsize(line, font=font)[0] # Fallback
                 
            line_x = (target_size[0] - line_width) // 2
            # Use the actual calculated height for this specific line for incrementing Y
            # Ensure index is valid before accessing line_heights
            if i < len(line_heights):
                 actual_line_height = line_heights[i] * (line_spacing_factor if i > 0 else 1.2)
            else:
                 # Fallback if line_heights calculation had an issue
                 logger.warning(f"Index {i} out of bounds for line_heights (length {len(line_heights)}). Using fallback height.")
                 actual_line_height = base_font_size * (line_spacing_factor if i > 0 else 1.2) # Less accurate fallback
                 
            logger.debug(f"  Line width={line_width}, calculated line_x={line_x}, actual_line_height={actual_line_height}")

            # --- Start Replace ---  (Replace old Style 1 logic)
            if style == 'style2':
                # Style 2: Golden text with enhanced shadow for readability
                # Make title larger for Style 2 but ensure it stays within boundaries
                style2_font_scale = 1.0 # Increased from 0.9 for larger text
                
                # Use EBGaramond-Bold.ttf specifically for Style 2
                style2_font = load_bundled_font(['EBGaramond-Bold.ttf'], int(base_font_size * style2_font_scale))
                # Use the specific font if successfully loaded, otherwise fallback to original font
                current_font = style2_font if style2_font else font
                
                # Ensure perfect centering for each line
                line_width = draw.textlength(line, font=current_font)
                adjusted_line_x = (target_size[0] - line_width) // 2
                
                # If text is too close to edges, adjust positioning
                if adjusted_line_x + line_width > target_size[0] - 40:  # 40px right margin
                    adjusted_line_x = max(40, target_size[0] - line_width - 40)  # Ensure minimum 40px from left
                
                # Change text color to golden (#d7bd45)
                style2_text_color = (215, 189, 69)  # #d7bd45 converted to RGB
                style2_shadow_color = (0, 0, 0, 150) # Darker shadow for better visibility (increased from 100)
                style2_shadow_offset = (4, 4) # Increased shadow offset for more depth (was 3,3)
                style2_stroke_color = (0, 0, 0, 255) # Black border
                
                # Enhanced shadow effect - multiple layers with decreasing opacity
                shadow_layers = [
                    ((5, 5), (0, 0, 0, 120)),  # Furthest shadow layer
                    ((4, 4), (0, 0, 0, 130)),  # Middle shadow layer
                    ((3, 3), (0, 0, 0, 150))   # Closest shadow layer
                ]
                
                # Draw multiple shadow layers for depth
                for offset, color in shadow_layers:
                    draw.text((adjusted_line_x + offset[0], current_y + offset[1]), 
                              line, fill=color, font=current_font)
                
                # Draw black border effect by drawing the text multiple times with slight offsets
                for offset_x, offset_y in [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
                    draw.text((adjusted_line_x + offset_x, current_y + offset_y), 
                            line, fill=style2_stroke_color, font=current_font)
                
                # Draw main text on top
                draw.text((adjusted_line_x, current_y), line, fill=style2_text_color, font=current_font)
            elif style == 'style3':
                # Style 3: Clean white text on black bars
                # Use Nunito-ExtraBold.ttf specifically for Style 3
                style3_font_scale = 1.1  # Scale up font size for Style 3 title
                
                # Reuse the font we already loaded earlier during bar height calculation
                current_font = temp_font if 'temp_font' in locals() else (
                    load_bundled_font(style3_font_preferences, int(base_font_size * style3_font_scale)) or font
                )
                
                # Ensure perfect centering for each line
                line_width = draw.textlength(line, font=current_font)
                adjusted_line_x = (target_size[0] - line_width) // 2
                
                # Ensure minimum margins
                if adjusted_line_x + line_width > target_size[0] - 40:
                    adjusted_line_x = max(40, target_size[0] - line_width - 40)
                
                # Pure white text for high contrast against black bar
                style3_text_color = (255, 255, 255)
                
                # Draw text with subtle shadow for depth
                shadow_offset = (2, 2)
                shadow_color = (0, 0, 0, 100)
                
                # Shadow for subtle depth
                draw.text((adjusted_line_x + shadow_offset[0], current_y + shadow_offset[1]),
                          line, fill=shadow_color, font=current_font)
                
                # Main text
                draw.text((adjusted_line_x, current_y), line, fill=style3_text_color, font=current_font)
            elif style == 'style4':
                # Style 4: Gold-colored text in the bottom rectangle using Vidaloka font
                style4_font_scale = 1.1  # Scale up font size for Style 4 title
                
                # Load Vidaloka font for Style 4
                style4_font = load_bundled_font(style4_font_preferences, int(base_font_size * style4_font_scale))
                # Use the specific font if successfully loaded, otherwise fallback to original font
                current_font = style4_font if style4_font else font
                logger.debug(f"  Style 4: Using font: {current_font.path if hasattr(current_font, 'path') else 'Default/Unknown'} at size {current_font.size if hasattr(current_font, 'size') else 'Unknown'}")
                
                # Ensure perfect centering for each line
                try:
                     line_width = draw.textlength(line, font=current_font)
                except AttributeError:
                     line_width = draw.textsize(line, font=current_font)[0] # Fallback
                adjusted_line_x = (target_size[0] - line_width) // 2
                logger.debug(f"  Style 4: Recalculated line_width={line_width}, adjusted_line_x={adjusted_line_x}")
                
                # If text is too close to edges, adjust positioning
                if adjusted_line_x < 40: # Check left edge
                     logger.debug(f"  Style 4: Adjusting line_x from {adjusted_line_x} to 40 (left bound)")
                     adjusted_line_x = 40
                elif adjusted_line_x + line_width > target_size[0] - 40:  # Check right edge
                     new_x = target_size[0] - line_width - 40
                     logger.debug(f"  Style 4: Adjusting line_x from {adjusted_line_x} to {new_x} (right bound)")
                     adjusted_line_x = max(40, new_x) # Ensure it doesn't go past left bound either

                # Use the specified gold color (#d7bd45)
                style4_text_color = (215, 189, 69)  # #d7bd45 converted to RGB
                
                # First draw a subtle shadow for depth against dark background
                shadow_offset = (2, 2)
                shadow_color = (0, 0, 0, 150)
                draw.text((adjusted_line_x + shadow_offset[0], current_y + shadow_offset[1]),
                          line, fill=shadow_color, font=current_font)
                
                # Main gold text
                draw.text((adjusted_line_x, current_y), line, fill=style4_text_color, font=current_font)
            elif style == 'style5':
                # Style 5: White bold text in the dark curved section using LeagueSpartan-Bold font
                style5_font_scale = 1.2  # Scale up font size for more impact
                
                # Load LeagueSpartan-Bold font for Style 5
                style5_font = load_bundled_font(style5_font_preferences, int(base_font_size * style5_font_scale))
                # Use the specific font if successfully loaded, otherwise fallback to original font
                current_font = style5_font if style5_font else font
                
                # Ensure perfect centering for each line
                line_width = draw.textlength(line, font=current_font)
                adjusted_line_x = (target_size[0] - line_width) // 2
                
                # If text is too close to edges, adjust positioning
                if adjusted_line_x + line_width > target_size[0] - 40:  # 40px right margin
                    adjusted_line_x = max(40, target_size[0] - line_width - 40)  # Ensure minimum 40px from left
                
                # Bright white text for high contrast against dark background
                style5_text_color = (255, 255, 255)  # Pure white
                
                # Add subtle shadow for depth
                shadow_offset = (3, 3)
                shadow_color = (0, 0, 0, 130)
                draw.text((adjusted_line_x + shadow_offset[0], current_y + shadow_offset[1]),
                          line, fill=shadow_color, font=current_font)
                
                # Main white text
                draw.text((adjusted_line_x, current_y), line, fill=style5_text_color, font=current_font)
            else: # Style 1
                # Style 1: White text with shadow
                shadow_offset = (4, 4)
                shadow_color = (0, 0, 0, 128)
                text_color = (255, 255, 255)
                # Shadow
                draw.text((line_x + shadow_offset[0], current_y + shadow_offset[1]),
                          line, fill=shadow_color, font=font)
                # Main text
                draw.text((line_x, current_y), line, fill=text_color, font=font)
            # --- End Replace ---

        # --- Final Touches ---
        # Apply professional shadow effect to the entire image for Style 2
        if style == 'style2':
            # Convert to RGBA if not already
            img = img.convert("RGBA")
            
            # Create a shadow layer
            shadow_layer = Image.new('RGBA', target_size, (0, 0, 0, 0))
            img_shadow = img.copy()
            
            # Create shadow by darkening the image copy
            shadow_opacity = 180  # Higher value = darker shadow
            shadow_overlay = Image.new('RGBA', target_size, (0, 0, 0, shadow_opacity))
            img_shadow = Image.alpha_composite(img_shadow, shadow_overlay)
            
            # Blur the shadow
            img_shadow = img_shadow.filter(ImageFilter.GaussianBlur(radius=15))
            
            # Create a new image for the composition
            composite = Image.new('RGBA', (target_size[0] + 20, target_size[1] + 20), (0, 0, 0, 0))
            
            # Place shadow offset behind the main image
            composite.paste(img_shadow, (10, 10))
            
            # Place the main image on top
            composite.paste(img, (0, 0))
            
            # Crop to remove excess shadow edges if needed
            img = composite.crop((0, 0, target_size[0], target_size[1]))
            
            # Apply rounded corners to the entire image
            img = add_rounded_corners(img) # Apply corners LAST
        elif style == 'style3':
            # Style 3 final touches - add subtle gradient to the bars for dimension
            img = img.convert("RGBA")
            
            # Apply rounded corners to the entire image with larger radius for more pronounced corners
            img = add_rounded_corners(img, radius=60)  # Increased from 40 to 60 for more pronounced corners
            
            # Ensure proper conversion back to RGB for saving
            img = img.convert("RGB")
        elif style == 'style4':
            # Style 4 final touches
            img = img.convert("RGBA")
            
            # Apply rounded corners to the entire image
            img = add_rounded_corners(img, radius=30)  # More subtle corners for this style
            
            # Ensure proper conversion back to RGB for saving
            img = img.convert("RGB")
        elif style == 'style5':
            # Style 5 final touches
            img = img.convert("RGBA")
            
            # Apply rounded corners to the entire image
            img = add_rounded_corners(img, radius=40)  # Medium rounded corners for this style
            
            # Ensure proper conversion back to RGB for saving
            img = img.convert("RGB")
        
        # Create a static directory if it doesn't exist - IMPROVED PATH HANDLING
        # First try using the absolute path method
        try:
            static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
            logger.info(f"Attempting to use static directory at: {static_dir}")
            
            # Check if this path is writeable
            if not os.access(os.path.dirname(static_dir), os.W_OK):
                logger.warning(f"No write access to {os.path.dirname(static_dir)}, trying alternate location")
                # Try an alternative location - current working directory
                static_dir = os.path.join(os.getcwd(), 'static')
                logger.info(f"Using alternative static directory at: {static_dir}")
            
            if not os.path.exists(static_dir):
                logger.info(f"Static directory doesn't exist. Creating at: {static_dir}")
                os.makedirs(static_dir, exist_ok=True)
                
            # Double check we can write to this directory
            if not os.access(static_dir, os.W_OK):
                logger.warning(f"No write access to {static_dir}, trying system temp directory")
                # Use system temp directory as last resort
                static_dir = os.path.join(tempfile.gettempdir(), 'flask_app_static')
                os.makedirs(static_dir, exist_ok=True)
                logger.info(f"Using system temp directory at: {static_dir}")
        except Exception as e:
            # Last resort - use system temp directory
            logger.error(f"Error setting up static directory: {e}")
            static_dir = os.path.join(tempfile.gettempdir(), 'flask_app_static')
            os.makedirs(static_dir, exist_ok=True)
            logger.info(f"Using system temp directory for static files: {static_dir}")
            
        # Log static directory permissions
        logger.info(f"Static directory permissions: {oct(os.stat(static_dir).st_mode)[-3:]}")
        
        # Generate a unique filename
        image_filename = f"generated_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
        image_path = os.path.join(static_dir, image_filename)
        
        # Save the image
        try:
            img.save(image_path, format='PNG')
            logger.info(f"Image saved to {image_path}")
        except Exception as e:
            logger.error(f"Failed to save image to {image_path}: {e}")
            # Try saving to system temp directory as last resort
            temp_dir = tempfile.gettempdir()
            image_path = os.path.join(temp_dir, image_filename)
            img.save(image_path, format='PNG')
            logger.info(f"Image saved to temp location: {image_path}")
        
        # Construct image URL with better URL handling for production environments
        # Check if we're behind a proxy
        proxy_path = os.environ.get('PROXY_PATH', '')
        if proxy_path:
            # If behind a proxy with a path, use that
            base_url = proxy_path.rstrip('/')
            image_url = f"{base_url}/static/{image_filename}"
        else:
            # Default behavior but make sure to include scheme, host and port
            # Get only host part excluding path if any
            host_url = request.host_url.rstrip('/')
            image_url = f"{host_url}/static/{image_filename}"
            
        logger.info(f"Generated image URL: {image_url}")
        
        # Update the static file path in a global registry for lookup later
        # This helps if the file is saved in a temp directory
        if not hasattr(app, 'static_file_registry'):
            app.static_file_registry = {}
        app.static_file_registry[image_filename] = image_path
        
        # Return JSON with image URL
        return jsonify({
            "image_url": image_url,
            "status": "success",
            "full_path": image_path  # Include full path for debugging
        })
    
    except Exception as e:
        logger.exception("Exception during image generation and processing")
        return jsonify({"error": f"Error processing image: {str(e)}"}), 500

# Improved route to serve static files
@app.route('/static/<path:filename>')
def serve_static(filename):
    # First try the registry for files in non-standard locations
    if hasattr(app, 'static_file_registry') and filename in app.static_file_registry:
        logger.info(f"Serving {filename} from registry path: {app.static_file_registry[filename]}")
        return send_file(app.static_file_registry[filename])
    
    # Try the standard static directory
    try:
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
        file_path = os.path.join(static_dir, filename)
        if os.path.exists(file_path):
            logger.info(f"Serving {filename} from standard static dir")
            return send_file(file_path)
    except Exception as e:
        logger.warning(f"Error looking for file in standard location: {e}")
    
    # Try alternate locations
    try:
        alt_static_dir = os.path.join(os.getcwd(), 'static')
        alt_file_path = os.path.join(alt_static_dir, filename)
        if os.path.exists(alt_file_path):
            logger.info(f"Serving {filename} from alternate static dir")
            return send_file(alt_file_path)
    except Exception as e:
        logger.warning(f"Error looking for file in alternate location: {e}")
    
    # Try temp directory
    try:
        temp_static_dir = os.path.join(tempfile.gettempdir(), 'flask_app_static')
        temp_file_path = os.path.join(temp_static_dir, filename)
        if os.path.exists(temp_file_path):
            logger.info(f"Serving {filename} from temp static dir")
            return send_file(temp_file_path)
    except Exception as e:
        logger.warning(f"Error looking for file in temp directory: {e}")
    
    # If all else fails
    logger.error(f"Static file {filename} not found in any location")
    return jsonify({"error": f"File {filename} not found"}), 404

# Modify the Flask run configuration at the bottom
if __name__ == '__main__':
    # Log environment info
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Script directory: {os.path.dirname(os.path.abspath(__file__))}")
    
    # In production, don't use debug mode
    port = int(os.environ.get('PORT', 5000))
    
    # Add option to configure the host
    host = os.environ.get('HOST', '0.0.0.0')
    logger.info(f"Starting Flask server on {host}:{port}")
    
    app.run(host=host, port=port, debug=(os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'))