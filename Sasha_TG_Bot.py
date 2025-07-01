import logging
import os
import pyshorteners
from moviepy import *
from moviepy.video.fx import Crop
from typing import cast
import time
import subprocess
import numpy as np
import asyncio

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile, Bot
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# States
CHOOSING, SHORTEN, VIDEO, VINYL_IMAGE, VINYL_AUDIO, UTM_URL, UTM_SOURCE, UTM_CAMPAIGN = range(8)

UTM_SOURCE_CHOICE, UTM_CAMPAIGN_CHOICE = range(8, 10)

# Keyboard
reply_keyboard = [['🔗', '🔗 UTM', '📷', '💿', '🛑']]
markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)

# Start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=markup)
    return CHOOSING

# Stop command
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Session stopped. Use /start to begin again.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# Menu command
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    current_state = "Unknown"
    if hasattr(context, 'user_data') and 'state' in context.user_data:
        state_map = {
            CHOOSING: "Main Menu", 
            SHORTEN: "Waiting for URL", 
            VIDEO: "Waiting for Video",
            VINYL_IMAGE: "Waiting for Vinyl Image",
            VINYL_AUDIO: "Waiting for Vinyl Audio",
            UTM_URL: "Waiting for UTM URL",
            UTM_SOURCE: "Waiting for UTM Source",
            UTM_CAMPAIGN: "Waiting for UTM Campaign"
        }
        current_state = state_map.get(context.user_data['state'], "Unknown")
    
    menu_text = f"📋 Current State: {current_state}\n\n"
    menu_text += "Available Commands:\n"
    menu_text += "/start - Start the bot\n"
    menu_text += "/stop - Stop the session\n"
    menu_text += "/menu - Show this menu\n"
    menu_text += "/cancel - Cancel current operation"
    
    await update.message.reply_text(menu_text)
    # Return current state or CHOOSING if unknown
    return context.user_data.get('state', CHOOSING)

# Handle choice
async def choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    context.user_data['state'] = CHOOSING

    if choice == '🔗':
        await update.message.reply_text("Send the URL to shorten:", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = SHORTEN
        return SHORTEN
    elif choice == '🔗 UTM':
        await update.message.reply_text("Creating UTM tracking URL!\n\nFirst, send the URL you want to track:", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = UTM_URL
        # Clear any previous UTM data
        context.user_data.pop('utm_url', None)
        context.user_data.pop('utm_source', None)
        context.user_data.pop('utm_campaign', None)
        return UTM_URL
    elif choice == '📷':
        await update.message.reply_text("Send a video (max 50MB, square, up to 1 minute):", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = VIDEO
        return VIDEO
    elif choice == '💿':
        await update.message.reply_text("Creating a vinyl record!\n\nFirst, send an image for the vinyl cover:", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = VINYL_IMAGE
        # Clear any previous vinyl data
        context.user_data.pop('vinyl_image_path', None)
        context.user_data.pop('vinyl_audio_path', None)
        return VINYL_IMAGE
    elif choice == '🛑':
        return await stop(update, context)
    else:
        await update.message.reply_text("Choose a valid option.", reply_markup=markup)
        return CHOOSING

# Handle URL shortening
async def shorten_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    long_url = update.message.text
    try:
        short_url = pyshorteners.Shortener().tinyurl.short(long_url)
        await update.message.reply_text(f"Shortened URL:\n{short_url}")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

    await update.message.reply_text("What next?", reply_markup=markup)
    context.user_data['state'] = CHOOSING
    return CHOOSING

# Handle UTM URL input
async def handle_utm_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    
    # Basic URL validation
    if not (url.startswith('http://') or url.startswith('https://')):
        await update.message.reply_text("Please send a valid URL starting with http:// or https://")
        return UTM_URL
    
    # Store the URL
    context.user_data['utm_url'] = url
    
    # Create source selection keyboard
    source_keyboard = [
        ['Yandex', 'VK', 'Google'],
        ['Enter custom value']
    ]
    source_markup = ReplyKeyboardMarkup(source_keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text("✅ URL received!\n\nSelect campaign source or choose to enter custom value:", reply_markup=source_markup)
    context.user_data['state'] = UTM_SOURCE_CHOICE
    return UTM_SOURCE_CHOICE

# New function to handle source selection
async def handle_utm_source_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip()
    
    if choice in ['Yandex', 'VK', 'Google']:
        # Store the selected source
        context.user_data['utm_source'] = choice.lower()
        return await proceed_to_campaign_choice(update, context)
    elif choice == 'Enter custom value':
        await update.message.reply_text("Enter your custom campaign source:", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = UTM_SOURCE
        return UTM_SOURCE
    else:
        # Invalid choice, show options again
        source_keyboard = [
            ['Yandex', 'VK', 'Google'],
            ['Enter custom value']
        ]
        source_markup = ReplyKeyboardMarkup(source_keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text("Please select from the options below:", reply_markup=source_markup)
        return UTM_SOURCE_CHOICE

# Handle UTM source input
async def handle_utm_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    source = update.message.text.strip()
    
    if not source:
        await update.message.reply_text("Please provide a campaign source (e.g., google, facebook, newsletter)")
        return UTM_SOURCE
    
    # Store the source
    context.user_data['utm_source'] = source.lower()
    
    return await proceed_to_campaign_choice(update, context)

# New function to handle campaign choice setup
async def proceed_to_campaign_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = context.user_data.get('utm_url', '')
    
    # Extract potential campaign name from URL
    try:
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip('/').split('/')
        suggested_campaign = path_parts[-1] if path_parts and path_parts[-1] else None
        
        if suggested_campaign:
            # Create campaign choice keyboard
            campaign_keyboard = [
                [f'Use: {suggested_campaign}'],
                ['Enter custom value']
            ]
            campaign_markup = ReplyKeyboardMarkup(campaign_keyboard, one_time_keyboard=True, resize_keyboard=True)
            
            context.user_data['suggested_campaign'] = suggested_campaign
            
            await update.message.reply_text(
                f"✅ Campaign source received!\n\n"
                f"I found '{suggested_campaign}' from your URL path.\n"
                f"Would you like to use it as campaign name or enter your own?", 
                reply_markup=campaign_markup
            )
        else:
            # No suggestion available, go directly to custom input
            await update.message.reply_text("✅ Campaign source received!\n\nNow send the campaign name (e.g., spring_sale, product_launch, holiday_promo):", reply_markup=ReplyKeyboardRemove())
            context.user_data['state'] = UTM_CAMPAIGN
            return UTM_CAMPAIGN
            
    except Exception:
        # Error parsing URL, go to custom input
        await update.message.reply_text("✅ Campaign source received!\n\nNow send the campaign name (e.g., spring_sale, product_launch, holiday_promo):", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = UTM_CAMPAIGN
        return UTM_CAMPAIGN
    
    context.user_data['state'] = UTM_CAMPAIGN_CHOICE
    return UTM_CAMPAIGN_CHOICE

# New function to handle campaign choice
async def handle_utm_campaign_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip()
    suggested_campaign = context.user_data.get('suggested_campaign', '')
    
    if choice == f'Use: {suggested_campaign}':
        # Use the suggested campaign name
        campaign = suggested_campaign
    elif choice == 'Enter custom value':
        await update.message.reply_text("Enter your custom campaign name:", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = UTM_CAMPAIGN
        return UTM_CAMPAIGN
    else:
        # Invalid choice, show options again
        campaign_keyboard = [
            [f'Use: {suggested_campaign}'],
            ['Enter custom value']
        ]
        campaign_markup = ReplyKeyboardMarkup(campaign_keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text("Please select from the options below:", reply_markup=campaign_markup)
        return UTM_CAMPAIGN_CHOICE
    
    # Generate the final UTM URL
    return await generate_utm_final_url(update, context, campaign)

# New function to generate final UTM URL
async def generate_utm_final_url(update: Update, context: ContextTypes.DEFAULT_TYPE, campaign: str) -> int:
    try:
        # Get stored data
        base_url = context.user_data.get('utm_url')
        utm_source = context.user_data.get('utm_source')
        utm_campaign = campaign
        
        # Build UTM URL
        utm_url = build_utm_url(base_url, utm_source, utm_campaign)
        
        # Shorten the UTM URL
        short_url = pyshorteners.Shortener().tinyurl.short(utm_url)
        
        # Create response message
        response_text = "🔗 UTM Tracking URL Created!\n\n"
        response_text += f"📊 **Tracking Details:**\n"
        response_text += f"• Source: `{utm_source}`\n"
        response_text += f"• Campaign: `{utm_campaign}`\n\n"
        response_text += f"🔗 **Full UTM URL:**\n`{utm_url}`\n\n"
        response_text += f"✂️ **Shortened URL:**\n{short_url}"
        
        await update.message.reply_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"Error creating UTM URL: {str(e)}")
    
    # Clear UTM data
    context.user_data.pop('utm_url', None)
    context.user_data.pop('utm_source', None)
    context.user_data.pop('utm_campaign', None)
    context.user_data.pop('suggested_campaign', None)
    
    await update.message.reply_text("What next?", reply_markup=markup)
    context.user_data['state'] = CHOOSING
    return CHOOSING

# Handle UTM campaign input and generate final URL
async def handle_utm_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    campaign = update.message.text.strip()
    
    if not campaign:
        await update.message.reply_text("Please provide a campaign name (e.g., spring_sale, product_launch)")
        return UTM_CAMPAIGN
    
    try:
        # Get stored data
        base_url = context.user_data.get('utm_url')
        utm_source = context.user_data.get('utm_source')
        utm_campaign = campaign
        
        # Build UTM URL
        utm_url = build_utm_url(base_url, utm_source, utm_campaign)
        
        # Shorten the UTM URL
        short_url = pyshorteners.Shortener().tinyurl.short(utm_url)
        
        # Create response message
        response_text = "🔗 UTM Tracking URL Created!\n\n"
        response_text += f"📊 **Tracking Details:**\n"
        response_text += f"• Source: `{utm_source}`\n"
        response_text += f"• Campaign: `{utm_campaign}`\n\n"
        response_text += f"🔗 **Full UTM URL:**\n`{utm_url}`\n\n"
        response_text += f"✂️ **Shortened URL:**\n{short_url}"
        
        await update.message.reply_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"Error creating UTM URL: {str(e)}")
    
    # Clear UTM data
    context.user_data.pop('utm_url', None)
    context.user_data.pop('utm_source', None)
    context.user_data.pop('utm_campaign', None)
    
    await update.message.reply_text("What next?", reply_markup=markup)
    context.user_data['state'] = CHOOSING
    return CHOOSING

# Build UTM URL with parameters
def build_utm_url(base_url: str, utm_source: str, utm_campaign: str) -> str:
    """Build URL with UTM parameters"""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    
    # Parse the URL
    parsed = urlparse(base_url)
    query_dict = parse_qs(parsed.query)
    
    # Add UTM parameters (convert to single values for urlencode)
    utm_params = {
        'utm_source': utm_source,
        'utm_campaign': utm_campaign,
        'utm_medium': 'smm'  # Default medium
    }
    
    # Add UTM parameters to existing query parameters
    for key, value in utm_params.items():
        query_dict[key] = [value]  # parse_qs returns lists, so we need lists
    
    # Convert back to query string
    new_query = urlencode(query_dict, doseq=True)
    
    # Rebuild URL
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)

# Handle video processing
async def process_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    video = update.message.video or update.message.document
    if not video:
        await update.message.reply_text("Please send a valid video file.")
        return VIDEO

    # Download video
    file = await video.get_file()
    input_path = "input_video.mp4"
    output_path = "round_video.mp4"
    await file.download_to_drive(input_path)

    # Crop and resize using moviepy
    try:
        clip = VideoFileClip(input_path)
        duration = min(clip.duration, 60)
        clip = cast(VideoFileClip, clip.subclipped(0, duration))
        size = min(clip.w, clip.h)
        crop_effect = Crop(x_center=clip.w / 2, y_center=clip.h / 2, width=size, height=size)
        clip = clip.with_effects([crop_effect])

        target_size = 512 if size > 512 else 240
        clip = clip.resized((target_size, target_size))
        
        # Write video with optimized settings for video notes
        clip.write_videofile(
            output_path, 
            codec="libx264", 
            audio_codec="aac",
            bitrate="500k",  # Lower bitrate for smaller file size
            fps=24           # Standard fps for video notes
        )
        clip.close()
        
    except Exception as e:
        await update.message.reply_text(f"Processing failed: {e}")
        context.user_data['state'] = CHOOSING
        return CHOOSING

    # Send as round video (video note)
    try:
        with open(output_path, 'rb') as video_file:
            await update.message.reply_video_note(
                video_file,
                duration=int(duration),
                length=target_size
            )
    except Exception as e:
        await update.message.reply_text(f"Failed to send video: {e}")

    # Clean up files
    if os.path.exists(input_path):
        os.remove(input_path)
    if os.path.exists(output_path):
        os.remove(output_path)

    await update.message.reply_text("Video note ready! Forward it to your channel.", reply_markup=markup)
    context.user_data['state'] = CHOOSING
    return CHOOSING

# Handle vinyl image upload
async def handle_vinyl_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check if user sent an image
    if not (update.message.photo or (update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('image/'))):
        await update.message.reply_text("Please send a valid image file (JPEG, PNG, etc.)")
        return VINYL_IMAGE
    
    try:
        # Get the image file
        if update.message.photo:
            # Get the largest photo size
            photo = update.message.photo[-1]
            file = await photo.get_file()
        else:
            # Document image
            file = await update.message.document.get_file()
        
        # Download image
        image_path = "vinyl_image." + file.file_path.split('.')[-1]
        await file.download_to_drive(image_path)
        
        # Store image path in user data
        context.user_data['vinyl_image_path'] = image_path
        
        await update.message.reply_text("✅ Image received! Now send an audio file (MP3, WAV, etc.):")
        context.user_data['state'] = VINYL_AUDIO
        return VINYL_AUDIO
        
    except Exception as e:
        await update.message.reply_text(f"Error processing image: {str(e)}")
        return VINYL_IMAGE

# Handle vinyl audio upload
async def handle_vinyl_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check if user sent an audio file
    audio = update.message.audio or update.message.voice or update.message.document
    
    if not audio:
        await update.message.reply_text("Please send a valid audio file (MP3, WAV, etc.)")
        return VINYL_AUDIO
    
    # Check if document is audio
    if hasattr(audio, 'mime_type') and audio.mime_type and not audio.mime_type.startswith('audio/'):
        await update.message.reply_text("Please send a valid audio file")
        return VINYL_AUDIO
    
    try:
        # Send initial processing message
        processing_msg = await update.message.reply_text("🎵 Processing vinyl... This may take a moment!")
        
        # Download audio
        file = await audio.get_file()
        audio_path = "vinyl_audio." + (file.file_path.split('.')[-1] if '.' in file.file_path else 'mp3')
        await file.download_to_drive(audio_path)
        
        # Store audio path
        context.user_data['vinyl_audio_path'] = audio_path
        
        # Create vinyl video with better error handling
        try:
            await create_vinyl_video_async(update, context, processing_msg)
        except asyncio.TimeoutError:
            # This shouldn't happen now, but just in case
            await update.message.reply_text("⚠️ Processing is taking longer than expected, but your vinyl is still being created...")
            # Continue processing in background
            asyncio.create_task(create_vinyl_video_background(update, context))
        
    except Exception as e:
        await update.message.reply_text(f"Error processing audio: {str(e)}")
        # Clean up files
        cleanup_vinyl_files(context)
        
    context.user_data['state'] = CHOOSING
    return CHOOSING

# Create spinning vinyl video with async handling
async def create_vinyl_video_async(update: Update, context: ContextTypes.DEFAULT_TYPE, processing_msg=None):
    """Main vinyl creation function with proper async handling"""
    try:
        # Run the heavy processing in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, create_vinyl_video_sync, update, context)
        
        if success:
            # Send the video
            await send_vinyl_video(update, context)
            if processing_msg:
                try:
                    await processing_msg.delete()
                except:
                    pass  # Ignore if message can't be deleted
        else:
            await update.message.reply_text("Failed to create vinyl video")
            
    except Exception as e:
        await update.message.reply_text(f"Failed to create vinyl: {str(e)}")
    finally:
        # Clean up all files
        cleanup_vinyl_files(context)

# Background task for vinyl creation (fallback)
async def create_vinyl_video_background(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Background task for when main processing times out"""
    try:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, create_vinyl_video_sync, update, context)
        
        if success:
            await send_vinyl_video(update, context)
        else:
            await update.message.reply_text("Failed to create vinyl video in background")
            
    except Exception as e:
        await update.message.reply_text(f"Background vinyl creation failed: {str(e)}")
    finally:
        cleanup_vinyl_files(context)

# Synchronous vinyl creation (the heavy lifting)
def create_vinyl_video_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Synchronous video creation that runs in thread pool"""
    image_path = context.user_data.get('vinyl_image_path')
    audio_path = context.user_data.get('vinyl_audio_path')
    output_path = "vinyl_video.mp4"
    vinyl_overlay_path = "vinyl_overlay.png"
    
    try:
        # Load audio and limit to 60 seconds
        audio_clip = AudioFileClip(audio_path)
        duration = min(audio_clip.duration, 60)
        audio_clip = audio_clip.subclipped(0, duration)
        
        # Load and process user's image
        user_image_clip = ImageClip(image_path, duration=duration)
        
        # Make user image square and resize
        size = min(user_image_clip.w, user_image_clip.h)
        crop_effect = Crop(x_center=user_image_clip.w / 2, y_center=user_image_clip.h / 2, width=size, height=size)
        user_image_clip = user_image_clip.with_effects([crop_effect])
        
        target_size = 512
        user_image_clip = user_image_clip.resized((target_size, target_size))
        
        # Create vinyl blend effect
        def create_vinyl_blend(get_frame, t):
            from PIL import Image as PILImage, ImageEnhance
            import numpy as np
            
            # Get user's image frame
            user_frame = get_frame(t)
            user_pil = PILImage.fromarray(user_frame.astype('uint8')).convert('RGB')
            
            # Load vinyl overlay (do this once and cache if needed)
            if os.path.exists(vinyl_overlay_path):
                vinyl_pil = PILImage.open(vinyl_overlay_path).convert('RGB')
                vinyl_pil = vinyl_pil.resize((target_size, target_size), PILImage.Resampling.LANCZOS)
                
                # Convert images to numpy arrays for blending
                user_array = np.array(user_pil, dtype=np.float32)
                vinyl_array = np.array(vinyl_pil, dtype=np.float32)
                
                # More color-preserving vinyl texture blend
                vinyl_strength = 0.4
                
                # Convert to HSV to preserve hue and saturation
                user_hsv = user_pil.convert('HSV')
                user_hsv_array = np.array(user_hsv, dtype=np.float32)
                
                # Apply vinyl texture only to the V (brightness) channel
                vinyl_gray = np.mean(vinyl_array, axis=2)
                vinyl_brightness_effect = (vinyl_gray - 128) * vinyl_strength * 0.5
                
                # Apply effect only to brightness channel
                user_hsv_array[:, :, 2] = np.clip(user_hsv_array[:, :, 2] + vinyl_brightness_effect, 0, 255)
                
                # Convert back to RGB
                result_hsv = PILImage.fromarray(user_hsv_array.astype('uint8'), 'HSV')
                blended_pil = result_hsv.convert('RGB')
                
                # Minimal post-processing to maintain colors
                enhancer = ImageEnhance.Contrast(blended_pil)
                blended_pil = enhancer.enhance(1.02)
                
                return np.array(blended_pil)
            else:
                return user_frame
        
        # Apply vinyl blend effect
        vinyl_blend_clip = user_image_clip.transform(create_vinyl_blend)
        
        # Create rotation effect
        def rotate_func(get_frame, t):
            frame = get_frame(t)
            angle = (t * 12) % 360
            
            from PIL import Image as PILImage
            import numpy as np
            
            pil_image = PILImage.fromarray(frame.astype('uint8'))
            rotated = pil_image.rotate(-angle, expand=False, fillcolor=(0, 0, 0))
            return np.array(rotated)
        
        # Apply rotation to the blended vinyl
        spinning_clip = vinyl_blend_clip.transform(rotate_func)
        
        # Combine with audio
        final_clip = spinning_clip.with_audio(audio_clip)
        
        # Write video with optimized settings
        final_clip.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            bitrate="500k",
            fps=24
        )
        
        # Clean up clips
        final_clip.close()
        audio_clip.close()
        user_image_clip.close()
        vinyl_blend_clip.close()
        spinning_clip.close()
        
        # Store output path for sending
        context.user_data['vinyl_output_path'] = output_path
        context.user_data['vinyl_duration'] = duration
        context.user_data['vinyl_target_size'] = target_size
        
        return True
        
    except Exception as e:
        print(f"Vinyl creation error: {e}")
        return False

# Send the completed vinyl video
async def send_vinyl_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the vinyl video as a video note"""
    try:
        output_path = context.user_data.get('vinyl_output_path', 'vinyl_video.mp4')
        duration = context.user_data.get('vinyl_duration', 30)
        target_size = context.user_data.get('vinyl_target_size', 512)
        
        if os.path.exists(output_path):
            with open(output_path, 'rb') as video_file:
                await update.message.reply_video_note(
                    video_file,
                    duration=int(duration),
                    length=target_size
                )
            
            await update.message.reply_text("🎵 Vinyl record created! Forward it to your channel.", reply_markup=markup)
            
            # Clean up output file
            os.remove(output_path)
        else:
            await update.message.reply_text("Vinyl video file not found")
            
    except Exception as e:
        await update.message.reply_text(f"Failed to send vinyl: {str(e)}")

# Clean up vinyl files
def cleanup_vinyl_files(context):
    image_path = context.user_data.get('vinyl_image_path')
    audio_path = context.user_data.get('vinyl_audio_path')
    output_path = context.user_data.get('vinyl_output_path', 'vinyl_video.mp4')
    
    for path in [image_path, audio_path, output_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass  # Ignore cleanup errors
    
    # Clear from user data
    context.user_data.pop('vinyl_image_path', None)
    context.user_data.pop('vinyl_audio_path', None)
    context.user_data.pop('vinyl_output_path', None)
    context.user_data.pop('vinyl_duration', None)
    context.user_data.pop('vinyl_target_size', None)

# Cancel
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Clean up any vinyl files if in vinyl creation process
    if context.user_data.get('state') in [VINYL_IMAGE, VINYL_AUDIO]:
        cleanup_vinyl_files(context)
    
    # Clean up UTM data if in UTM creation process
    if context.user_data.get('state') in [UTM_URL, UTM_SOURCE, UTM_CAMPAIGN]:
        context.user_data.pop('utm_url', None)
        context.user_data.pop('utm_source', None)
        context.user_data.pop('utm_campaign', None)
    
    await update.message.reply_text("Operation cancelled. What next?", reply_markup=markup)
    context.user_data['state'] = CHOOSING
    return CHOOSING

# Main
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_action),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            SHORTEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, shorten_url),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            VIDEO: [
                MessageHandler(filters.VIDEO | filters.Document.VIDEO, process_video),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            VINYL_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_vinyl_image),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            VINYL_AUDIO: [
                MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, handle_vinyl_audio),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            UTM_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utm_url),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            UTM_SOURCE_CHOICE: [  # NEW STATE
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utm_source_choice),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            UTM_SOURCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utm_source),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            UTM_CAMPAIGN_CHOICE: [  # NEW STATE
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utm_campaign_choice),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
            UTM_CAMPAIGN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utm_campaign),
                CommandHandler("menu", menu),
                CommandHandler("stop", stop),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("stop", stop),
        ],
    )

    app.add_handler(conv_handler)
    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()