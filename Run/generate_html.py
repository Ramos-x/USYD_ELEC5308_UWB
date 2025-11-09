#!/usr/bin/env python3
"""
Markdown to HTML Presentation Converter
Converts any Markdown file to interactive HTML slides
Usage: python generate_html.py [input.md] [output.html]
"""

import sys
import os
import re
import base64
import markdown2

def embed_images_as_base64(html_content, base_dir):
    """
    Find all image tags and convert local images to base64 data URIs

    Args:
        html_content: HTML content with image tags
        base_dir: Base directory for resolving relative image paths

    Returns:
        HTML content with embedded base64 images
    """
    # Pattern to match img tags
    img_pattern = re.compile(r'<img\s+src="([^"]+)"([^>]*)>', re.IGNORECASE)

    def replace_image(match):
        img_path = match.group(1)
        img_attrs = match.group(2)

        # Skip if already a data URI or external URL
        if img_path.startswith('data:') or img_path.startswith('http://') or img_path.startswith('https://'):
            return match.group(0)

        # Resolve relative path
        if img_path.startswith('./'):
            img_path = img_path[2:]

        full_path = os.path.join(base_dir, img_path)

        # Check if file exists
        if not os.path.exists(full_path):
            print(f"    [!] Warning: Image not found: {full_path}")
            return match.group(0)

        try:
            # Read image and convert to base64
            with open(full_path, 'rb') as img_file:
                img_data = img_file.read()
                img_base64 = base64.b64encode(img_data).decode('utf-8')

            # Detect MIME type from extension
            ext = os.path.splitext(full_path)[1].lower()
            mime_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.svg': 'image/svg+xml',
                '.webp': 'image/webp'
            }
            mime_type = mime_types.get(ext, 'image/png')

            # Create data URI
            data_uri = f'data:{mime_type};base64,{img_base64}'

            print(f"    [+] Embedded image: {img_path} ({len(img_data) / 1024:.1f} KB)")

            return f'<img src="{data_uri}"{img_attrs}>'

        except Exception as e:
            print(f"    [-] Error embedding image {img_path}: {e}")
            return match.group(0)

    return img_pattern.sub(replace_image, html_content)

def generate_html_presentation(input_file, output_file):
    """
    Generate interactive HTML presentation from Markdown

    Args:
        input_file: Path to input Markdown file
        output_file: Path to output HTML file
    """

    print(f"[*] Reading: {input_file}")

    # Read Markdown content
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            md_content = f.read()
    except FileNotFoundError:
        print(f"[-] Error: File not found: {input_file}")
        return False
    except Exception as e:
        print(f"[-] Error reading file: {e}")
        return False

    # Split into slides by "---"
    slides = md_content.split('\n---\n')
    print(f"[+] Found {len(slides)} slides")

    # HTML template with embedded CSS and JavaScript
    html_template = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UWB Indoor Positioning System - Presentation</title>
    <style>
        /* Reset and base styles */
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            overflow: hidden;
            color: #333;
        }}

        /* Presentation container */
        .presentation {{
            width: 100vw;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}

        /* Individual slide */
        .slide {{
            display: none;
            width: 92%;
            max-width: 1250px;
            height: 87vh;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 40px 50px;
            overflow-y: auto;
            animation: slideIn 0.5s ease;
        }}

        .slide.active {{
            display: block;
        }}

        @keyframes slideIn {{
            from {{
                opacity: 0;
                transform: translateY(20px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}

        /* Typography */
        h1 {{
            color: #1F4788;
            font-size: 2.3em;
            margin-bottom: 18px;
            text-align: center;
            border-bottom: 3px solid #4472C4;
            padding-bottom: 12px;
        }}

        h2 {{
            color: #2E5090;
            font-size: 1.9em;
            margin: 25px 0 12px 0;
            border-left: 5px solid #4472C4;
            padding-left: 12px;
        }}

        h3 {{
            color: #4472C4;
            font-size: 1.4em;
            margin: 18px 0 8px 0;
        }}

        p, li {{
            font-size: 1.05em;
            line-height: 1.7;
            color: #333;
            margin-bottom: 8px;
        }}

        ul, ol {{
            margin-left: 25px;
            margin-bottom: 15px;
        }}

        li {{
            margin-bottom: 6px;
        }}

        /* Code styling */
        code {{
            background: #f5f5f5;
            padding: 2px 5px;
            border-radius: 3px;
            font-family: 'Courier New', 'Consolas', monospace;
            color: #d73a49;
            font-size: 0.9em;
        }}

        pre {{
            background: #2d2d2d;
            color: #f8f8f2;
            padding: 15px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 12px 0;
            font-size: 0.85em;
            line-height: 1.4;
        }}

        pre code {{
            background: none;
            color: inherit;
            padding: 0;
        }}

        /* Table styling */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            font-size: 0.95em;
        }}

        table th {{
            background: #4472C4;
            color: white;
            padding: 10px;
            text-align: left;
            font-weight: bold;
        }}

        table td {{
            padding: 8px 10px;
            border-bottom: 1px solid #ddd;
        }}

        table tr:nth-child(even) {{
            background: #f9f9f9;
        }}

        table tr:hover {{
            background: #f0f0f0;
        }}

        /* Blockquote */
        blockquote {{
            border-left: 5px solid #4472C4;
            background: #f0f4ff;
            padding: 12px 15px;
            margin: 15px 0;
            font-style: italic;
            color: #1F4788;
            font-size: 1.1em;
        }}

        /* Bold and emphasis */
        strong {{
            color: #d73a49;
            font-weight: bold;
        }}

        em {{
            font-style: italic;
            color: #666;
        }}

        /* Links */
        a {{
            color: #4472C4;
            text-decoration: none;
            border-bottom: 1px solid #4472C4;
        }}

        a:hover {{
            color: #2E5090;
            border-bottom-color: #2E5090;
        }}

        /* Images */
        img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 20px auto;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}

        /* Image with alt text png */
        img[alt="png"] {{
            max-height: 450px;
            object-fit: contain;
        }}

        /* Controls */
        .controls {{
            position: fixed;
            bottom: 25px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 12px;
            z-index: 1000;
        }}

        .controls button {{
            background: white;
            border: 2px solid #4472C4;
            color: #4472C4;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.95em;
            font-weight: bold;
            transition: all 0.3s ease;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}

        .controls button:hover {{
            background: #4472C4;
            color: white;
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.3);
        }}

        .controls button:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }}

        /* Slide counter */
        .slide-counter {{
            position: fixed;
            top: 18px;
            right: 25px;
            background: white;
            padding: 8px 18px;
            border-radius: 20px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            font-weight: bold;
            color: #4472C4;
            z-index: 1000;
            font-size: 1em;
        }}

        /* Help overlay */
        .help {{
            position: fixed;
            top: 18px;
            left: 25px;
            background: rgba(255,255,255,0.9);
            padding: 8px 15px;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            font-size: 0.85em;
            color: #666;
            z-index: 1000;
        }}

        .help kbd {{
            background: #4472C4;
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
            font-size: 0.9em;
        }}

        /* Responsive design */
        @media (max-width: 768px) {{
            .slide {{
                width: 95%;
                padding: 25px 20px;
                height: 90vh;
            }}

            h1 {{ font-size: 1.8em; }}
            h2 {{ font-size: 1.5em; }}
            h3 {{ font-size: 1.2em; }}
            p, li {{ font-size: 1em; }}

            .controls {{
                bottom: 15px;
            }}

            .controls button {{
                padding: 8px 15px;
                font-size: 0.85em;
            }}

            .help {{
                display: none;
            }}
        }}

        /* Scrollbar styling */
        .slide::-webkit-scrollbar {{
            width: 8px;
        }}

        .slide::-webkit-scrollbar-track {{
            background: #f1f1f1;
            border-radius: 10px;
        }}

        .slide::-webkit-scrollbar-thumb {{
            background: #4472C4;
            border-radius: 10px;
        }}

        .slide::-webkit-scrollbar-thumb:hover {{
            background: #2E5090;
        }}
    </style>
</head>
<body>
    <!-- Help indicator -->


    <!-- Slide counter -->
    <div class="slide-counter">
        <span id="current-slide">1</span> / <span id="total-slides">{len(slides)}</span>
    </div>

    <!-- Presentation container -->
    <div class="presentation">'''

    # Convert each slide from Markdown to HTML
    print("[*] Converting slides to HTML...")
    base_dir = os.path.dirname(os.path.abspath(input_file))

    for idx, slide_md in enumerate(slides):
        # Convert markdown to HTML with extras
        slide_html = markdown2.markdown(
            slide_md,
            extras=['fenced-code-blocks', 'tables', 'break-on-newline']
        )

        # Embed images as base64
        slide_html = embed_images_as_base64(slide_html, base_dir)

        # Wrap in slide div
        active_class = 'active' if idx == 0 else ''
        html_template += f'''
        <div class="slide {active_class}">
{slide_html}
        </div>'''

    # Add controls and JavaScript
    html_template += '''
    </div>

    <!-- Navigation controls -->
    <div class="controls">
        <button id="prev-btn" onclick="previousSlide()">◀ Previous</button>
        <button id="next-btn" onclick="nextSlide()">Next ▶</button>
    </div>

    <script>
        // Slide navigation logic
        let currentSlide = 0;
        const slides = document.querySelectorAll('.slide');
        const totalSlides = slides.length;

        function showSlide(n) {
            // Remove active class from current slide
            slides[currentSlide].classList.remove('active');

            // Calculate new slide index (with wrapping)
            currentSlide = (n + totalSlides) % totalSlides;

            // Add active class to new slide
            slides[currentSlide].classList.add('active');

            // Update counter
            document.getElementById('current-slide').textContent = currentSlide + 1;

            // Update button states
            document.getElementById('prev-btn').disabled = currentSlide === 0;
            document.getElementById('next-btn').disabled = currentSlide === totalSlides - 1;
        }

        function nextSlide() {
            if (currentSlide < totalSlides - 1) {
                showSlide(currentSlide + 1);
            }
        }

        function previousSlide() {
            if (currentSlide > 0) {
                showSlide(currentSlide - 1);
            }
        }

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowRight' || e.key === ' ') {
                e.preventDefault();
                nextSlide();
            } else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                previousSlide();
            } else if (e.key === 'Home') {
                e.preventDefault();
                showSlide(0);
            } else if (e.key === 'End') {
                e.preventDefault();
                showSlide(totalSlides - 1);
            }
        });

        // Initialize
        showSlide(0);

        console.log(`Presentation loaded: ${totalSlides} slides`);
    </script>
</body>
</html>'''

    # Write HTML file
    print(f"[*] Writing: {output_file}")
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_template)
    except Exception as e:
        print(f"[-] Error writing file: {e}")
        return False

    print(f"[+] Success! HTML presentation created")
    print(f"[+] Total slides: {len(slides)}")
    print(f"[+] File size: {os.path.getsize(output_file) / 1024:.1f} KB")
    print(f"\n[!] Open '{output_file}' in your browser to view")
    return True


def main():
    """Main entry point"""

    # Default files
    default_input = 'PRESENTATION.md'
    default_output = 'PRESENTATION.html'

    # Parse command line arguments
    if len(sys.argv) >= 2:
        input_file = sys.argv[1]
    else:
        input_file = default_input

    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        # Auto-generate output filename
        output_file = os.path.splitext(input_file)[0] + '.html'

    print("=" * 60)
    print("Markdown to HTML Presentation Generator")
    print("=" * 60)

    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"\n[-] Error: Input file '{input_file}' not found")
        print(f"\nUsage: python {sys.argv[0]} [input.md] [output.html]")
        print(f"\nExample:")
        print(f"  python {sys.argv[0]} PRESENTATION.md")
        print(f"  python {sys.argv[0]} my_slides.md my_presentation.html")
        return 1

    # Generate HTML
    success = generate_html_presentation(input_file, output_file)

    if success:
        print("\n" + "=" * 60)
        print("Presentation Controls:")
        print("  - Arrow keys (left/right) to navigate")
        print("  - Spacebar to go next")
        print("  - Home/End to jump to first/last slide")
        print("  - F11 for fullscreen")
        print("=" * 60)
        return 0
    else:
        return 1


if __name__ == '__main__':
    sys.exit(main())