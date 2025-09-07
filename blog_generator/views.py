# ==========================
# Blog Generator Views
# ==========================
# This file handles:
# - YouTube audio + caption extraction
# - Whisper transcription (local model)
# - Gemini API blog generation
# - Blog CRUD views (list, detail, save)
# - User authentication (login/signup/logout)

import json
import os
import uuid
from urllib.parse import parse_qs, urlparse
from concurrent.futures import ThreadPoolExecutor
import asyncio
import hashlib

import whisper
import yt_dlp # for ffmpeg support: https://www.gyan.dev/ffmpeg/builds/#release-builds
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from google import genai

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import redirect, render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache

from .models import BlogPost



# ==========================
# Global Config
# ==========================

# Load Whisper model globally (so it loads once at server start, not per request).
# Available sizes: tiny, base, small, medium, large.
# Tradeoff: larger = more accurate but slower & more memory.
whisper_model = whisper.load_model("tiny")

# Global thread pool for blocking tasks (tune max_workers for your CPU cores)
executor = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)

async def run_in_thread(fn, *args):
    """Run a blocking function in the thread pool"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, fn, *args)



# ==========================
# Views
# ==========================

@login_required
def index(request):
    """Render home/index page."""
    return render(request, 'index.html')

@csrf_exempt
def generate_blog(request):
    """
    Main API endpoint to generate a blog post from a YouTube video.
    Workflow:
    1. Extract video title.
    2. Fetch captions & Whisper transcript.
    3. Send transcripts to Gemini for blog writing.
    4. Save generated blog in database.
    5. Return JSON with blog content.
    """
    if request.method != "POST" :
        return JsonResponse( {'error': 'Invalid request method'}, status = 405 )

    try:
        data = json.loads(request.body)                             # Parse incoming JSON request body
        yt_link = data['link']                                      # Extract YouTube link

        if not yt_link:
            return JsonResponse({'error': 'YouTube link is required'}, status=400)

    except (KeyError, json.JSONDecodeError):
        return JsonResponse( {'error': 'Invalid data sent' }, status=400)
    
    try:
        title = yt_title(yt_link)                           # Fetch YouTube video title
        
        # Run async transcription pipeline inside sync view   
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running → safe to call asyncio.run()
            captions_text, whisper_text = asyncio.run(get_transcriptions(yt_link))
        else:
            # Already inside an event loop → schedule and wait
            task = loop.create_task(get_transcriptions(yt_link))
            captions_text, whisper_text = loop.run_until_complete(task)

        if not (captions_text or whisper_text):
            return JsonResponse({'error': "Failed to get transcript"}, status=500 )

        # Send transcripts to Gemini for blog generation
        blog_content = generate_blog_from_transcription(captions_text, whisper_text) # Send to Gemini

        if not blog_content:
            return JsonResponse({'error': "Failed to generate blog article"}, status = 500 )
        
        # Save to database
        BlogPost.objects.create(
            user=request.user,
            youtube_title=title,
            youtube_link=yt_link,
            generated_content=blog_content,
        )

        return JsonResponse( { 'content' : blog_content } )
    
    except Exception as e:  
        import traceback
        error_details = traceback.format_exc()
        print("Error in generate_blog:\n", error_details)           # full log in console
        return JsonResponse({'error': "Internal server error"}, status=500)

# ==========================
# Helper Functions
# ==========================

def extract_video_id(url):
    """
    Extract YouTube video ID from either:
    - full YouTube URL (https://www.youtube.com/watch?v=...)
    - short URL (https://youtu.be/...)
    Returns:
        str: video ID or None if not found
    """
    parsed = urlparse(url)
    if "youtube" in parsed.netloc:
        return parse_qs(parsed.query).get("v", [None])[0]
    elif "youtu.be" in parsed.netloc:
        return parsed.path.strip("/")
    return None

def yt_title(link):
    """
    Get YouTube video title using yt_dlp.
    Args:
        link (str): YouTube video URL
    Returns:
        str: video title (or "Untitled Video" if not found)
    """
    try:
        ydl_opts = {"quiet": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
        return info.get("title", "Untitled Video")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch YouTube title: {str(e)}")

def download_audio(video_url):
    """
    Download audio from YouTube video using yt_dlp.
    - First saves as a temporary `.webm` file for Whisper input.
    - Also stores a `.mp3` copy in MEDIA_ROOT for persistence (only while    development).
    Returns:
        str: path to temporary audio file (for Whisper transcription)
    """
    try:
        output_file = f"audio_{uuid.uuid4().hex}.webm"      # Temporary file for Whisper

        ydl_opts = {
            "format" : "bestaudio/best",
            "outtmpl" : output_file,
            "quiet" : True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # Only in development → also keep an .mp3
        if settings.DEBUG:
            mp3_file = os.path.join(settings.MEDIA_ROOT, f"audio_{uuid.uuid4().hex}.mp3")   # Permanent copy in MEDIA_ROOT as .mp3
            ydl_opts_mp3 = {
                "format": "bestaudio/best",
                "outtmpl": mp3_file,
                "quiet": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
            with yt_dlp.YoutubeDL(ydl_opts_mp3) as ydl:         # Run ffmpeg postprocessor to convert to mp3
                ydl.download([video_url])

        return output_file
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("Audio download failed:\n", error_details)    # Full error in Django logs
        raise RuntimeError("Audio download failed. Ensure FFmpeg is installed and on PATH.")

def get_youtube_captions(video_id, lang="en"):
    """
    Fetch captions from YouTube if available.
    Args:
        video_id (str): YouTube video ID
        lang (str): caption language (default: English)
    Returns:
        str: joined captions text or "" if unavailable
    """
    try:
         # Try preferred language first
        captions = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
        return " ".join([t['text'] for t in captions]).strip()
    except NoTranscriptFound:
        print(f"[YouTube Captions] No '{lang}' transcript found, trying auto-generated…")
        try:
            # Get all transcripts for this video
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

            # Try auto-generated English if available
            if transcript_list.find_generated_transcript([lang]):
                captions = transcript_list.find_generated_transcript([lang]).fetch()
                return " ".join([t['text'] for t in captions]).strip()

        except Exception as e:
            print(f"[YouTube Captions] Auto-generated transcript failed: {e}")
            return ""

    except TranscriptsDisabled:
        print(f"[YouTube Captions] Captions disabled for {video_id}")
        return ""

    except Exception as e:
        print(f"[YouTube Captions] Unexpected error for {video_id}: {e}")
        return "" # fallback → Whisper will handle
    return ""

def transcribe_whisper(audio_file):
    """
    Run Whisper transcription on a given audio file.
    Args:
        audio_file (str): path to audio file
    Returns:
        str: transcribed text
    """
    try:
        result = whisper_model.transcribe(audio_file)           # Run Whisper on audio file
        return result["text"].strip()                           # Extract cleaned transcript
    except Exception as e:
        raise RuntimeError(f"Whisper transcription failed: {str(e)}")

async def get_transcriptions(video_url, lang="en"):
    """
    Async transcription pipeline:
    1. Try YouTube captions (if available).
    2. Always run Whisper on downloaded audio.
    3. Captions + audio download in parallel
    4. Whisper runs after audio is ready
    5. Return both results (captions_text, whisper_text).
    Returns:
        tuple(str, str): captions_text, whisper_text
    Raises:
        RuntimeError: if both methods fail
    """
    try:
        video_id = extract_video_id(video_url)                  # Parse YouTube video ID
        if not video_id:
            raise RuntimeError("Invalid YouTube URL")
        
        cache_key = f"transcriptions:{video_id}:{lang}"
        cached = cache.get(cache_key)
        if cached:
            return cached  # (captions_text, whisper_text)
        
        captions_text, whisper_text, audio_file = "", "", ""
        
        captions_task = asyncio.create_task(run_in_thread(get_youtube_captions, video_id, lang))
        audio_task = asyncio.create_task(run_in_thread(download_audio, video_url))
        captions_text, audio_file = await asyncio.gather(captions_task, audio_task)

        whisper_text = await run_in_thread(transcribe_whisper, audio_file)

        # Clean up temporary audio file
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except Exception:
                pass # Ignore cleanup errors

        if not (captions_text or whisper_text):
            raise RuntimeError("Both captions and Whisper failed")
    
        result = (captions_text, whisper_text)
        cache.set(cache_key, result, timeout=86400)  # cache for 1 day
        return result
    
    except Exception as e:
        raise RuntimeError(f"Fetching transcriptions failed: {str(e)}") 

def generate_blog_from_transcription(captions_text, whisper_text):
    """
    Merge transcripts & generate blog post using Gemini API.
    Steps:
    - Merge captions + Whisper into clean transcript.
    - Ask Gemini to rewrite as a professional blog post.
    Returns:
        str: generated blog content
    Raises:
        RuntimeError: if Gemini API fails
    """

    cache_key = "blog:" + hashlib.sha256((captions_text + whisper_text).encode()).hexdigest()
    cached_blog = cache.get(cache_key)
    if cached_blog:
        return cached_blog
    
    # Construct prompt with both transcripts (captions + Whisper)
    prompt = f"""
    You are a professional transcription editor and blog writer.
    I have two transcripts of the same YouTube video:

    --- Captions Transcript ---
    {captions_text or '[EMPTY]'}

    --- Whisper Transcript ---
    {whisper_text or '[EMPTY]'}

    First you are a professional transcription editor.
    Please merge these into one clean, perfect, accurate transcript.
    - Fix mistakes
    - remove repetitions
    - ensure readability

    Then you are a professional blog writer. 
    You always write clear, engaging, and well-structured articles.
    Based on that merged transcript, write a comprehensive blog article.
    - take input from the above transcript created
    - Make it engaging, well-structured, and professional
    - Do NOT mention YouTube or that it’s a transcript or youtube video 
    - Write it like a properly polished blog post

    Finally you do the following:
    - You do not give the transcript in the output
    - You only give blog generated as output
    """

    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))      # Init Gemini client
        response = client.models.generate_content(
            model = "gemini-2.5-flash",                                 # Free, lightweight model
            contents = prompt
        )
        # ✅ Safer parsing
        candidates = getattr(response, "candidates", [])
        if not candidates or not getattr(candidates[0], "content", None):
            raise RuntimeError("Gemini API returned no valid content")

        parts = getattr(candidates[0].content, "parts", [])
        if not parts:
            raise RuntimeError("Gemini API returned empty parts")

        content = getattr(candidates[0], "content", None)
        if not content or not getattr(content, "parts", []):
            raise RuntimeError("Gemini API returned no content parts")

        blog_content = "".join(getattr(p, "text", "") for p in parts).strip()

        if not blog_content:
            raise RuntimeError("Gemini API returned empty blog content")

        cache.set(cache_key, blog_content, timeout=86400)  # cache for 1 day
        return blog_content
    
    except Exception as e:
        raise RuntimeError(f"Gemini API request failed: {str(e)}")

# ==========================
# Blog CRUD
# ==========================
def blog_list(request):
    """
    Show list of all blog posts created by the logged-in user.
    """
    blog_articles = BlogPost.objects.filter(user = request.user)
    return render(request, "all-blogs.html", {'blog_articles': blog_articles})

def blog_details(request, pk):
    """
    Show details of a single blog post.
    Access restricted to the post's owner.
    """
    # blog_article_detail = BlogPost.objects.get(id=pk)
    blog_article_detail = get_object_or_404(BlogPost, id=pk)
    if request.user != blog_article_detail.user:
        return HttpResponseForbidden("You do not have permission to view this blog")
    return render(request, "blog-details.html", {'blog_article_detail': blog_article_detail})

@login_required
def blog_delete(request, pk):
    """
    Delete a single blog post.
    Access restricted to the post's owner.
    - GET → show confirmation page
    - POST → actually delete the blog
    """
    blog_article = get_object_or_404(BlogPost, id=pk)

    if request.user != blog_article.user:
        return HttpResponseForbidden("You do not have permission to delete this blog")
      
    if request.method == "POST":
        blog_article.delete()
        messages.success(request, "Blog deleted successfully")
        return redirect("blog-list")  # 👈 redirect back to blog list after deletion
    
    return render(request, "blog-delete.html", {"blog_article": blog_article})

# ==========================
# User Authentication
# ==========================

def user_login(request):
    """
    Handle user login.
    - GET → render login form
    - POST → authenticate & log in
    """
    if request.method == "POST" :
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)  # Check credentials
        if user is not None:
            login(request, user)                                            # Log the user in if valid
            return redirect('/')
        else:
            error_message = "Invalid username or password"
            return render(request, 'login.html', {'error_message':error_message})
    return render(request, 'login.html')


def user_signup(request):
    """
    Handle user signup.
    - GET → render signup form
    - POST → create user account, validate passwords, log in
    """
    if request.method == "POST" :
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        repeatPassword = request.POST['repeatPassword']
        if User.objects.filter(username=username).exists():
            return render(request, 'signup.html', {'error_message': 'Username already exists'})
        if password == repeatPassword:                                      # Validate password match
            try:
                user = User.objects.create_user(username, email, password)  # Create new user
                user.save()
                login(request, user)                                        # Auto login after signup
                return redirect('/')                                        # Re-directed to Home page
            except Exception as e:
                error_message = 'Error creating account'
                return render(request, 'signup.html', {'error_message':error_message} )
        
        else:
            error_message = "Passwords do not match"
            return render( request, 'signup.html', {'error_message':error_message} ) 
    return render(request, 'signup.html')


def user_logout(request):
    """
    Log out current user and redirect to home page.
    """
    logout(request)
    return redirect('/')