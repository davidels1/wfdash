from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size, text="WFS", bg_color="#0066cc", text_color="#FFFFFF"):
    # Create new image with background
    image = Image.new('RGB', (size, size), bg_color)
    draw = ImageDraw.Draw(image)
    
    # Calculate font size (approximate)
    font_size = int(size * 0.4)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    # Get text size
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    # Calculate text position (center)
    x = (size - text_width) / 2
    y = (size - text_height) / 2
    
    # Draw text
    draw.text((x, y), text, font=font, fill=text_color)
    
    return image

def generate_all_icons():
    # Create directory if it doesn't exist
    output_dir = "static/images/pwa"
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate all required icons
    sizes = {
        'icon-192x192.png': 192,
        'icon-512x512.png': 512,
        'apple-touch-icon.png': 180,
        'favicon-32x32.png': 32,
        'favicon-16x16.png': 16
    }
    
    for filename, size in sizes.items():
        icon = create_icon(size)
        icon.save(os.path.join(output_dir, filename))

if __name__ == "__main__":
    generate_all_icons()