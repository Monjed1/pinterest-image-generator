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

# Setup logging
logging.basicConfig(level=logging.INFO)
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
            style3_font_scale = 1.0  # Reduced from 1.1 to ensure text fits better in the box
            style3_font = load_bundled_font(style3_font_preferences, int(base_font_size * style3_font_scale))
            temp_font = style3_font if style3_font else font
            
            # Calculate wrapped text height
            temp_draw = ImageDraw.Draw(Image.new('RGB', (1,1)))
            max_text_width = target_size[0] - 100  # Increased padding from 80 to 100 for better fit
            
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
            # Convert to RGBA for adding elements
            img = img.convert('RGBA')
            
            # Define dimensions for bottom rectangle
            bottom_rect_height = 450  # Bottom dark rectangle height
            
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
        line_heights = [draw.textbbox((0,0), line, font=font)[3] - draw.textbbox((0,0), line, font=font)[1] for line in wrapped_lines]
        line_spacing_factor = 1.3
        total_text_height = sum(lh * line_spacing_factor for lh in line_heights) - (line_heights[0] * (line_spacing_factor - 1.2)) # Adjust first line spacing
        available_height = target_size[1]
        
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
            # bottom_rect_height = 450 # Already defined
            
            # New calculation: Position near top of the dark rectangle + padding
            top_padding_in_rect = 60 # Increase padding from top of rectangle
            text_y = target_size[1] - bottom_rect_height + top_padding_in_rect
            logger.debug(f"Style 4: Calculated text_y based on top alignment = {text_y}")
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
            bg_color = (0, 0, 0, 180)  # Increased opacity to match example
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

            # Make the box wider to match example
            box_padding_sides = 50
            
            # Calculate box dimensions
            box_left = int(text_block_bbox[0] - box_padding_sides)
            box_top = int(text_block_bbox[1] - padding)
            box_right = int(text_block_bbox[2] + box_padding_sides)
            box_bottom = int(text_block_bbox[3] + padding * 0.8)
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
        for i, line in enumerate(wrapped_lines):
            line_width = draw.textlength(line, font=font)
            line_x = (target_size[0] - line_width) // 2
            actual_line_height = line_heights[i] * (line_spacing_factor if i > 0 else 1.2)
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
                # Style 3 - use white text on black bars with Nunito or similar font
                style3_font_scale = 1.0  # Reduced from 1.1 for better fit
                style3_font = load_bundled_font(style3_font_preferences, int(base_font_size * style3_font_scale))
                # Use the specific font if successfully loaded, otherwise fallback to original font
                current_font = style3_font if style3_font else font
                
                # Ensure perfect centering for each line
                line_width = draw.textlength(line, font=current_font)
                adjusted_line_x = (target_size[0] - line_width) // 2
                
                # Ensure minimum margins
                if adjusted_line_x + line_width > target_size[0] - 50:  # Increased from 40 to 50
                    adjusted_line_x = max(50, target_size[0] - line_width - 50)  # Ensure minimum 50px from sides
                
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
                
                # Ensure perfect centering for each line
                line_width = draw.textlength(line, font=current_font)
                adjusted_line_x = (target_size[0] - line_width) // 2
                
                # If text is too close to edges, adjust positioning
                if adjusted_line_x + line_width > target_size[0] - 40:  # 40px right margin
                    adjusted_line_x = max(40, target_size[0] - line_width - 40)  # Ensure minimum 40px from left
                
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
                # Style 1: Gold text with shadow to match example
                # Use a slightly different font preference for Style 1
                style1_font_scale = 1.05  # Slightly larger font
                style1_font = load_bundled_font(['LeagueSpartan-Bold.ttf', 'Montserrat-Bold.ttf'], 
                                               int(base_font_size * style1_font_scale))
                # Use the specific font if successfully loaded, otherwise fallback to original font
                current_font = style1_font if style1_font else font
                
                # Ensure perfect centering for each line
                line_width = draw.textlength(line, font=current_font)
                adjusted_line_x = (target_size[0] - line_width) // 2
                
                # Gold color like in the example
                style1_text_color = (215, 189, 69)  # Gold color (#d7bd45)
                shadow_offset = (3, 3)
                shadow_color = (0, 0, 0, 150)
                
                # Shadow
                draw.text((adjusted_line_x + shadow_offset[0], current_y + shadow_offset[1]),
                          line, fill=shadow_color, font=current_font)
                # Main text
                draw.text((adjusted_line_x, current_y), line, fill=style1_text_color, font=current_font)
            # --- End Replace ---

            # !!! IMPORTANT: Re-insert the missing Y increment here !!!
            current_y += actual_line_height

        # --- Create dark bottom bar for Style 1 before any other elements ---
        if style == 'style1' and branding_url:
            # Define dark bar at bottom for branding URL
            bottom_bar_height = 60  # Height of bottom bar
            bottom_bar_color = (0, 0, 0, 200)  # Semi-transparent black, darker than before
            
            # Create the box
            bottom_bar = Image.new('RGBA', (target_size[0], bottom_bar_height), bottom_bar_color)
            
            # Overlay the bar at the bottom of the image
            img.paste(bottom_bar, (0, target_size[1] - bottom_bar_height), bottom_bar)
            
            # Update drawing context
            draw = ImageDraw.Draw(img)

        # --- Create dark bottom bar for Style 2 as well ---
        if style == 'style2' and branding_url:
            # Define dark bar at bottom for branding URL
            bottom_bar_height = 60  # Height of bottom bar
            bottom_bar_color = (0, 0, 0, 200)  # Semi-transparent black
            
            # Create the box
            bottom_bar = Image.new('RGBA', (target_size[0], bottom_bar_height), bottom_bar_color)
            
            # Overlay the bar at the bottom of the image
            img.paste(bottom_bar, (0, target_size[1] - bottom_bar_height), bottom_bar)
            
            # Update drawing context
            draw = ImageDraw.Draw(img)

        # --- Draw Branding URL (Re-added from previous version) --- 
        if branding_url:
             logger.info(f"Drawing branding URL: {branding_url}")
             # Use the `current_y` value which marks the position *after* the last title line was drawn
             title_bottom_y = current_y 
             logger.debug(f"Position after last title line (current_y) = {title_bottom_y}")

             try:
                  # Skip drawing for Style 4 if already handled in final touches
                  if style == 'style4' and 'style4_branding_done' in locals() and style4_branding_done:
                      logger.info("Skipping regular branding URL draw for Style 4 - already handled in golden box")
                      pass
                  elif style == 'style5' and 'style5_branding_done' in locals() and style5_branding_done:
                      logger.info("Skipping regular branding URL draw for Style 5 - already handled in white box")
                      pass
                  else:
                      # Define branding font and size
                      branding_font_size = 30  # Default size for branding
                      
                      if style == "style1":
                          # Use the same font as the title and adjust size to fit in the bottom box
                          branding_font_size = 36  # Reduced from 40 to fit better in the bottom box
                          branding_font_preferences = ['LeagueSpartan-Bold.ttf', 'Montserrat-Bold.ttf']
                      elif style == "style2":
                          # Increase font size for Style 2 branding URL but ensure it fits well
                          branding_font_size = 38  # Adjusted from 45 to fit better
                          branding_font_preferences = ['EBGaramond-Bold.ttf', 'LeagueSpartan-Bold.ttf', 'Montserrat-Bold.ttf']
                      
                      branding_font = load_bundled_font(branding_font_preferences, branding_font_size)
                      if not branding_font:
                           logger.warning("Branding font failed to load, using default.")
                           # Use Pillow default with size if possible
                           try:
                               branding_font = ImageFont.load_default(size=branding_font_size)
                           except TypeError:
                               branding_font = ImageFont.load_default() # Older Pillow
                           
                      # Calculate text width
                      try:
                          branding_width = draw.textlength(branding_url, font=branding_font)
                      except AttributeError:
                          branding_width = draw.textsize(branding_url, font=branding_font)[0]
                          
                      # Get text height
                      try:
                           bbox = draw.textbbox((0,0), branding_url, font=branding_font)
                           text_height = bbox[3] - bbox[1]
                      except AttributeError:
                           text_height = branding_font_size # Fallback height

                      # Center text horizontally
                      branding_x = (target_size[0] - branding_width) // 2
                      
                      # Position branding text based on style
                      if style == 'style4':
                          # For Style 4, position below the title text with spacing
                          padding_below_title = 50  # Increased padding below title for Style 4
                          
                          # Use golden box for branding URL instead of directly drawing text
                          # Set font to a more appropriate one for a box display
                          style4_branding_font_size = 40  # Good size for visibility in the box
                          style4_branding_font_preferences = style4_font_preferences  # Use same font preferences as title
                          style4_branding_font = load_bundled_font(style4_branding_font_preferences, style4_branding_font_size)
                          
                          try:
                              # Make sure we have a draw object for the current image state
                              draw = ImageDraw.Draw(img)
                              
                              # Calculate dimensions
                              style4_branding_width = draw.textlength(branding_url, font=style4_branding_font)
                              style4_bbox = draw.textbbox((0,0), branding_url, font=style4_branding_font)
                              style4_text_height = style4_bbox[3] - style4_bbox[1]
                              
                              # Define golden box dimensions with padding
                              box_padding_x = 60  # Horizontal padding (30px on each side)
                              box_padding_y = 20  # Vertical padding (10px on top and bottom)
                              box_width = style4_branding_width + box_padding_x
                              box_height = style4_text_height + box_padding_y
                              
                              # Center box horizontally
                              box_x = (target_size[0] - box_width) // 2
                              
                              # Position at bottom of image with more padding from title
                              box_bottom_padding = 30  # Reduced padding from bottom to move box lower
                              box_y = target_size[1] - box_bottom_padding - box_height
                              
                              # Golden color for the box (like in the image)
                              gold_color = (230, 190, 60, 255)  # Bright gold color
                              
                              # Draw the box with slight rounding
                              box_rect = [(box_x, box_y), (box_x + box_width, box_y + box_height)]
                              draw.rounded_rectangle(box_rect, radius=5, fill=gold_color)
                              
                              # Calculate text position using bounding box for accurate centering
                              box_center_x = box_x + (box_width / 2)
                              box_center_y = box_y + (box_height / 2)
                              
                              # Calculate text position using bounding box for accurate centering
                              style4_branding_x = int(box_center_x - (style4_branding_width / 2))
                              
                              # Adjust Y position based on bounding box for more accurate centering
                              # This helps account for the text baseline which can make text appear off-center
                              # First determine the text's baseline offset
                              ascent = style4_text_height * 0.75  # Approximate ascent for most fonts
                              
                              # Position text with baseline correction to center it vertically
                              style4_branding_y = int(box_center_y - (style4_text_height / 2))
                              
                              # Apply additional vertical adjustment to fix centering if needed
                              vertical_adjustment = -5  # Adjust if text still appears too low
                              style4_branding_y += vertical_adjustment
                              
                              logger.info(f"Box: x={box_x}, y={box_y}, w={box_width}, h={box_height}")
                              logger.info(f"Box center: ({box_center_x}, {box_center_y})")
                              logger.info(f"Text dimensions: w={style4_branding_width}, h={style4_text_height}")
                              logger.info(f"Adjusted text pos: ({style4_branding_x}, {style4_branding_y})")
                              
                              # Draw text in black with precise positioning
                              draw.text((style4_branding_x, style4_branding_y), 
                                      branding_url, fill=(0, 0, 0, 255), font=style4_branding_font)
                              
                              # This approach bypasses the regular branding URL drawing code
                              # Set a flag to prevent double-drawing
                              style4_branding_done = True
                              
                          except Exception as e:
                              logger.error(f"Error drawing Style 4 golden branding box: {e}")
                              style4_branding_done = False
                      elif style == 'style3':
                          # For Style 3, position above the bottom black box (not inside it)
                          bottom_bar_height = 180  # Must match the value from style3 implementation
                          bottom_bar_top = target_size[1] - bottom_bar_height
                          
                          # Position button above the black box with some padding
                          padding_above_box = 30  # Space between button and top of black box
                          button_y = bottom_bar_top - button_height - padding_above_box
                          
                          # Use same font as title for branding URL
                          branding_font_size = 50  # Increased size for better visibility
                          branding_font_preferences = style3_font_preferences  # Use the same font preferences as the title
                          branding_font = load_bundled_font(branding_font_preferences, branding_font_size)
                          
                          # Reset branding_x for Style 3 since it might be overwritten
                          branding_x = None
                          
                          # Recalculate text dimensions with the new font
                          try:
                              branding_width = draw.textlength(branding_url, font=branding_font)
                              bbox = draw.textbbox((0,0), branding_url, font=branding_font)
                              text_height = bbox[3] - bbox[1]
                              
                              # Center text in the bottom bar both horizontally and vertically
                              branding_x = (target_size[0] - branding_width) // 2
                              # Calculate vertical center of the bottom bar
                              bottom_bar_center_y = bottom_bar_top + (bottom_bar_height // 2)
                              # Position text centered vertically in the bar
                              branding_y = bottom_bar_center_y - (text_height // 2)
                              
                              logger.info(f"Style 3 branding URL will be drawn at x={branding_x}, y={branding_y}")
                          except:
                              logger.warning("Could not recalculate branding text dimensions")
                              # Fallback positioning if calculation fails
                              branding_x = (target_size[0] // 2)  # Center horizontally
                              padding_from_bottom = 40
                              branding_y = target_size[1] - padding_from_bottom - text_height
                          
                          # Use white text color to match the title
                          branding_text_color = (255, 255, 255, 255)  # Full opacity white for better visibility
                      elif style == 'style5':
                          # For Style 5, position near the bottom of the curved dark section
                          padding_from_bottom = 50  # Padding from bottom of the image
                          branding_y = target_size[1] - padding_from_bottom - text_height
                          
                          # Use white text to match the title, slightly transparent
                          branding_text_color = (255, 255, 255, 220)
                      elif style == 'style2':
                          # For Style 2, position in the bottom dark bar (similar to Style 1)
                          bottom_bar_height = 60  # Must match the bottom bar height defined earlier
                          padding_from_bottom = 12  # Adjusted from 15 to center better in the bar
                          branding_y = target_size[1] - (bottom_bar_height / 2) - (text_height / 2)
                          
                          # Use light gold or white text for better contrast against the dark background
                          branding_text_color = (255, 240, 180, 255)  # Light gold color
                      elif style == 'style1':
                          # For Style 1, position in the bottom dark bar
                          bottom_bar_height = 60  # Must match the bottom bar height defined earlier
                          padding_from_bottom = 12  # Adjusted from 15 to center better in the bar
                          branding_y = target_size[1] - (bottom_bar_height / 2) - (text_height / 2)
                          
                          # Use gold text color to match the title
                          branding_text_color = (215, 189, 69, 255)  # Gold color (#d7bd45)
                      else:
                          # Default positioning from bottom for other styles (fallback)
                          padding_bottom = 30
                          branding_y = target_size[1] - text_height - padding_bottom
                          branding_text_color = (200, 200, 200)  # Light gray for other styles
                      
                      logger.debug(f"Branding text width={branding_width}, height={text_height}")
                      logger.debug(f"Drawing branding at x={branding_x}, y={branding_y}")
                      
                      # Define shadow effects based on style
                      if style == 'style1' or style == 'style2':
                          # Stronger shadow for styles 1 and 2 that might need more contrast
                          # Multi-layer shadow for better visibility in these styles
                          shadow_layers = [
                              ((3, 3), (0, 0, 0, 100)),
                              ((2, 2), (0, 0, 0, 130)),
                              ((1, 1), (0, 0, 0, 150))
                          ]
                          
                          for offset, color in shadow_layers:
                              draw.text((branding_x + offset[0], branding_y + offset[1]), 
                                      branding_url, fill=color, font=branding_font)
                      else:
                          # Default shadow for other styles
                          branding_shadow_color = (0, 0, 0, 100)
                          branding_shadow_offset = (2, 2)  # Increased from (1,1) for better visibility
                          draw.text((branding_x + branding_shadow_offset[0], branding_y + branding_shadow_offset[1]), 
                                  branding_url, fill=branding_shadow_color, font=branding_font)
                      
                      # Draw main text
                      logger.info(f"Drawing branding URL main text at x={branding_x}, y={branding_y}")
                      draw.text((branding_x, branding_y), branding_url, fill=branding_text_color, font=branding_font)
                      
             except Exception as e:
                  logger.error(f"Error drawing branding URL: {e}", exc_info=True)

        # --- Add "Read More" button for Style 1 ---
        if style == 'style1' or style == 'style2' or style == 'style3':
            # Calculate button position - centered below title
            read_more_text = "Read More"
            button_font_size = 33  # Reduced from 32 to fit better in container
            
            # Set appropriate font based on style
            if style == 'style1':
                # Use the same font as the title for Style 1
                button_font = load_bundled_font(['LeagueSpartan-Bold.ttf', 'Montserrat-Bold.ttf'], button_font_size)
            elif style == 'style2':
                # Use EBGaramond for Style 2 to match title
                button_font = load_bundled_font(['EBGaramond-Bold.ttf', 'LeagueSpartan-Bold.ttf'], button_font_size)
            else:  # style3
                # Use the same font as Style 3 title
                button_font = load_bundled_font(style3_font_preferences, button_font_size)
            
            try:
                # Calculate button text dimensions
                button_text_width = draw.textlength(read_more_text, font=button_font)
                text_bbox = draw.textbbox((0, 0), read_more_text, font=button_font)
                button_text_height = text_bbox[3] - text_bbox[1]
                
                # Create the button rectangle and shadow for a visual "button" effect
                button_width = int(target_size[0] * 0.45)  # Increased width from 0.4 to 0.45
                button_height = 70  # Increased height from 60 to 70
                button_x = (target_size[0] - button_width) // 2  # Center horizontally
                
                # Position button vertically based on style
                if style == 'style1':
                    # Position button lower on the image for Style 1
                    button_y = int(target_size[1] * 0.88)  # 88% down the image (changed from 80%)
                elif style == 'style2':
                    # Position button lower on the image for Style 2 too
                    button_y = int(target_size[1] * 0.85)  # 85% down the image
                else:  # style3
                    # For Style 3, position above the bottom black box (not inside it)
                    bottom_bar_height = 180  # Must match the value from style3 implementation
                    bottom_bar_top = target_size[1] - bottom_bar_height
                    
                    # Position button above the black box with some padding
                    padding_above_box = 30  # Space between button and top of black box
                    button_y = bottom_bar_top - button_height - padding_above_box
                
                # Create button overlay
                button_overlay = Image.new('RGBA', target_size, (0, 0, 0, 0))
                button_draw = ImageDraw.Draw(button_overlay)
                
                # Draw button background with rounded corners
                button_rect = [
                    (button_x, button_y),
                    (button_x + button_width, button_y + button_height)
                ]
                
                # Draw button shadow
                shadow_offset = 4
                shadow_color = (0, 0, 0, 90)
                shadow_rect = [
                    (button_x + shadow_offset, button_y + shadow_offset),
                    (button_x + button_width + shadow_offset, button_y + button_height + shadow_offset)
                ]
                button_draw.rounded_rectangle(shadow_rect, radius=25, fill=shadow_color)
                
                # Draw button background - adjust color based on style
                if style == 'style1':
                    button_color = (200, 200, 200, 240)  # Light gray with higher opacity
                elif style == 'style2':
                    button_color = (230, 220, 180, 240)  # Cream color that complements the gold
                else:  # style3
                    button_color = (220, 220, 220, 240)  # Light gray to contrast with the black box
                
                button_draw.rounded_rectangle(button_rect, radius=25, fill=button_color)
                
                # Overlay button on image
                img = Image.alpha_composite(img, button_overlay)
                draw = ImageDraw.Draw(img)
                
                # Draw button text - centered in button
                text_x = button_x + (button_width - button_text_width) // 2
                text_y = button_y + (button_height - button_text_height) // 2
                
                # Ensure perfect centering by applying a small adjustment if needed
                # This addresses potential rounding issues with certain font renderings
                text_x = int(text_x)
                text_y = int(text_y)
                
                # Text color based on style
                if style == 'style1':
                    text_color = (80, 80, 80)  # Darker gray text
                elif style == 'style2':
                    text_color = (90, 80, 50)  # Dark gold/brown text
                else:  # style3
                    text_color = (50, 50, 50)  # Nearly black text for good contrast
                
                # Draw text
                draw.text((text_x, text_y), read_more_text, fill=text_color, font=button_font)
                
            except Exception as e:
                logger.error(f"Error drawing 'Read More' button or bottom bar: {e}", exc_info=True)

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
        elif style == 'style1':
            # Style 1 final touches - add rounded corners for Pinterest suitability
            img = img.convert("RGBA")
            
            # Apply more pronounced rounded corners - increased radius for Pinterest-style rounding
            img = add_rounded_corners(img, radius=60)
            
            # Ensure proper conversion back to RGB for saving
            img = img.convert("RGB")
        elif style == 'style3':
            # Style 3 final touches - add subtle gradient to the bars for dimension
            img = img.convert("RGBA")
            
            # Apply rounded corners to the entire image with larger radius for more pronounced corners
            img = add_rounded_corners(img, radius=60)  # Increased from 40 to 60 for more pronounced corners
            
            # --- Specific fix for Style 3 branding URL ---
            if branding_url:
                # Make sure we have a draw object for the current image state
                draw = ImageDraw.Draw(img)
                
                # Use same font as title but larger for better visibility
                style3_branding_font_size = 60  # Very large for visibility
                style3_branding_font = load_bundled_font(style3_font_preferences, style3_branding_font_size)
                
                # Calculate dimensions
                try:
                    style3_branding_width = draw.textlength(branding_url, font=style3_branding_font)
                    style3_bbox = draw.textbbox((0,0), branding_url, font=style3_branding_font)
                    style3_text_height = style3_bbox[3] - style3_bbox[1]
                    
                    # Calculate position in bottom bar
                    bottom_bar_height = 180  # Must match the value used earlier
                    bottom_bar_top = target_size[1] - bottom_bar_height
                    style3_branding_x = (target_size[0] - style3_branding_width) // 2
                    style3_branding_y = bottom_bar_top + (bottom_bar_height - style3_text_height) // 2
                    
                    logger.info(f"STYLE 3 FIX: Drawing branding at x={style3_branding_x}, y={style3_branding_y}")
                    
                    # Add shadow for better visibility
                    shadow_offset = 3
                    draw.text((style3_branding_x + shadow_offset, style3_branding_y + shadow_offset), 
                            branding_url, fill=(0, 0, 0, 150), font=style3_branding_font)
                    
                    # Draw the branding URL with full opacity white
                    draw.text((style3_branding_x, style3_branding_y), 
                            branding_url, fill=(255, 255, 255, 255), font=style3_branding_font)
                except Exception as e:
                    logger.error(f"Style 3 branding URL fix error: {e}")
            
            # Ensure proper conversion back to RGB for saving
            img = img.convert("RGB")
        elif style == 'style4':
            # Style 4 final touches
            img = img.convert("RGBA")
            
            # Apply rounded corners to the entire image
            img = add_rounded_corners(img, radius=30)  # More subtle corners for this style
            
            # Add golden box for branding URL if present
            if branding_url:
                # Use the same font as the title for consistency
                style4_branding_font_size = 40  # Good size for visibility in the box
                style4_branding_font_preferences = style4_font_preferences  # Use same font preferences as title
                style4_branding_font = load_bundled_font(style4_branding_font_preferences, style4_branding_font_size)
                
                try:
                    # Make sure we have a draw object for the current image state
                    draw = ImageDraw.Draw(img)
                    
                    # Calculate dimensions
                    style4_branding_width = draw.textlength(branding_url, font=style4_branding_font)
                    style4_bbox = draw.textbbox((0,0), branding_url, font=style4_branding_font)
                    style4_text_height = style4_bbox[3] - style4_bbox[1]
                    
                    # Define golden box dimensions with padding
                    box_padding_x = 60  # Horizontal padding (30px on each side)
                    box_padding_y = 20  # Vertical padding (10px on top and bottom)
                    box_width = style4_branding_width + box_padding_x
                    box_height = style4_text_height + box_padding_y
                    
                    # Center box horizontally
                    box_x = (target_size[0] - box_width) // 2
                    
                    # Position at bottom of image with more padding from title
                    box_bottom_padding = 30  # Reduced padding from bottom to move box lower
                    box_y = target_size[1] - box_bottom_padding - box_height
                    
                    # Golden color for the box (like in the image)
                    gold_color = (230, 190, 60, 255)  # Bright gold color
                    
                    # Draw the box with slight rounding
                    box_rect = [(box_x, box_y), (box_x + box_width, box_y + box_height)]
                    draw.rounded_rectangle(box_rect, radius=5, fill=gold_color)
                    
                    # Calculate text position using bounding box for accurate centering
                    box_center_x = box_x + (box_width / 2)
                    box_center_y = box_y + (box_height / 2)
                    
                    # Calculate text position using bounding box for accurate centering
                    style4_branding_x = int(box_center_x - (style4_branding_width / 2))
                    
                    # Adjust Y position based on bounding box for more accurate centering
                    # This helps account for the text baseline which can make text appear off-center
                    # First determine the text's baseline offset
                    ascent = style4_text_height * 0.75  # Approximate ascent for most fonts
                    
                    # Position text with baseline correction to center it vertically
                    style4_branding_y = int(box_center_y - (style4_text_height / 2))
                    
                    # Apply additional vertical adjustment to fix centering if needed
                    vertical_adjustment = -5  # Adjust if text still appears too low
                    style4_branding_y += vertical_adjustment
                    
                    logger.info(f"Box: x={box_x}, y={box_y}, w={box_width}, h={box_height}")
                    logger.info(f"Box center: ({box_center_x}, {box_center_y})")
                    logger.info(f"Text dimensions: w={style4_branding_width}, h={style4_text_height}")
                    logger.info(f"Adjusted text pos: ({style4_branding_x}, {style4_branding_y})")
                    
                    # Draw text in black with precise positioning
                    draw.text((style4_branding_x, style4_branding_y), 
                            branding_url, fill=(0, 0, 0, 255), font=style4_branding_font)
                    
                    # This approach bypasses the regular branding URL drawing code
                    # Set a flag to prevent double-drawing
                    style4_branding_done = True
                    
                except Exception as e:
                    logger.error(f"Error drawing Style 4 golden branding box: {e}")
                    style4_branding_done = False
            
            # Ensure proper conversion back to RGB for saving
            img = img.convert("RGB")
        elif style == 'style5':
            # Style 5 final touches - add rounded corners for Pinterest suitability
            img = img.convert("RGBA")
            
            # Apply rounded corners to the entire image
            img = add_rounded_corners(img, radius=40)  # Medium rounded corners for this style
            
            # Add white box for branding URL if present
            if branding_url:
                # Use the same font as the title for consistency
                style5_branding_font_size = 40  # Good size for visibility in the box
                style5_branding_font_preferences = style5_font_preferences  # Use same font preferences as title
                style5_branding_font = load_bundled_font(style5_branding_font_preferences, style5_branding_font_size)
                
                try:
                    # Make sure we have a draw object for the current image state
                    draw = ImageDraw.Draw(img)
                    
                    # Calculate dimensions
                    style5_branding_width = draw.textlength(branding_url, font=style5_branding_font)
                    style5_bbox = draw.textbbox((0,0), branding_url, font=style5_branding_font)
                    style5_text_height = style5_bbox[3] - style5_bbox[1]
                    
                    # Define white box dimensions with padding
                    box_padding_x = 60  # Horizontal padding (30px on each side)
                    box_padding_y = 20  # Vertical padding (10px on top and bottom)
                    box_width = style5_branding_width + box_padding_x
                    box_height = style5_text_height + box_padding_y
                    
                    # Center box horizontally
                    box_x = (target_size[0] - box_width) // 2
                    
                    # Position at bottom of image with padding - adjust for style5 curved section
                    box_bottom_padding = 40  # Padding from bottom of image
                    box_y = target_size[1] - box_bottom_padding - box_height
                    
                    # White color for the box with slight transparency for style
                    white_color = (255, 255, 255, 245)  # Almost fully opaque white
                    
                    # Draw the box with slight rounding
                    box_rect = [(box_x, box_y), (box_x + box_width, box_y + box_height)]
                    draw.rounded_rectangle(box_rect, radius=8, fill=white_color)
                    
                    # Calculate text position using bounding box for accurate centering
                    box_center_x = box_x + (box_width / 2)
                    box_center_y = box_y + (box_height / 2)
                    
                    # Calculate text position using bounding box for accurate centering
                    style5_branding_x = int(box_center_x - (style5_branding_width / 2))
                    
                    # Position text with baseline correction to center it vertically
                    style5_branding_y = int(box_center_y - (style5_text_height / 2))
                    
                    # Apply additional vertical adjustment to fix centering if needed
                    vertical_adjustment = -5  # Adjust if text still appears too low
                    style5_branding_y += vertical_adjustment
                    
                    # Get more precise text measurements for perfect centering
                    # Recalculate using textbbox for the specific text string
                    text_bbox = draw.textbbox((0, 0), branding_url, font=style5_branding_font)
                    precise_width = text_bbox[2] - text_bbox[0]
                    precise_height = text_bbox[3] - text_bbox[1]
                    
                    # Calculate text position for perfect centering
                    style5_branding_x = int(box_center_x - (precise_width / 2))
                    
                    # For perfect vertical centering, account for font metrics
                    # The vertical adjustment is now positive to move text down from the top
                    vertical_adjustment = 8  # Changed from -8 to +8 to move text down
                    style5_branding_y = int(box_center_y - (precise_height / 2)) + vertical_adjustment
                    
                    logger.info(f"Style 5 box center at ({box_center_x}, {box_center_y})")
                    logger.info(f"Branding text position at ({style5_branding_x}, {style5_branding_y})")
                    
                    # Draw text in black with precise positioning for perfect centering
                    draw.text((style5_branding_x, style5_branding_y), 
                            branding_url, fill=(0, 0, 0, 255), font=style5_branding_font)
                    
                    # This approach bypasses the regular branding URL drawing code
                    # Set a flag to prevent double-drawing
                    style5_branding_done = True
                    
                except Exception as e:
                    logger.error(f"Error drawing Style 5 white branding box: {e}")
                    style5_branding_done = False
            else:
                style5_branding_done = False
            
            # Ensure proper conversion back to RGB for saving
            img = img.convert("RGB")
        
        # Create a static directory if it doesn't exist
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
        
        # Generate a unique filename
        image_filename = f"generated_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
        image_path = os.path.join(static_dir, image_filename)
        
        # Save the image
        img.save(image_path, format='PNG')
        
        # Construct image URL
        # Note: This assumes the server is configured to serve static files
        # In a production environment, you might want to use a CDN or dedicated file server
        host_url = request.host_url.rstrip('/')
        image_url = f"{host_url}/static/{image_filename}"
        
        logger.info(f"Image saved to {image_path}")
        
        # Return JSON with image URL
        return jsonify({
            "image_url": image_url,
            "status": "success"
        })
    
    except Exception as e:
        logger.exception("Exception during image generation and processing")
        return jsonify({"error": f"Error processing image: {str(e)}"}), 500

# Add a route to serve static files
@app.route('/static/<path:filename>')
def serve_static(filename):
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    return send_file(os.path.join(static_dir, filename))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000) 


# Add at the end of app.py
if __name__ == '__main__':
    # In production, don't use debug mode
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)