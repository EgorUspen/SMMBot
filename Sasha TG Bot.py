import logging
import os
import pyshorteners
from moviepy import *
from moviepy.video.fx import Crop
from typing import cast
import time
import subprocess
import numpy as np

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile, Bot
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)


# States
CHOOSING, SHORTEN, VIDEO = range(3)

# Keyboard
reply_keyboard = [['Generate short URL', 'Generate round video', 'Stop session']]
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
        state_map = {CHOOSING: "Main Menu", SHORTEN: "Waiting for URL", VIDEO: "Waiting for Video"}
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

    if choice == 'Generate short URL':
        await update.message.reply_text("Send the URL to shorten:", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = SHORTEN
        return SHORTEN
    elif choice == 'Generate round video':
        await update.message.reply_text("Send a video (max 50MB, square, up to 1 minute):", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = VIDEO
        return VIDEO
    elif choice == 'Stop session':
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

# Cancel
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled. What next?", reply_markup=markup)
    context.user_data['state'] = CHOOSING
    return CHOOSING

# Main
def main():
    # Use environment variable for production, fallback to your token for development
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
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