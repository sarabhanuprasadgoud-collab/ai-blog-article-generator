from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class BlogPost(models.Model):
    """
    Stores blog articles generated from YouTube videos + AI.
    Each blog is linked to a User (author).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)    # Owner of the blog post
    youtube_title = models.CharField(max_length=300)            # Original YouTube video title
    youtube_link = models.URLField()                            # YouTube video URL
    generated_content = models.TextField()                      # Final AI-generated blog content
    created_at = models.DateTimeField(auto_now_add=True)        # Timestamp when blog was created
    updated_at = models.DateTimeField(auto_now=True)            # Timestamp when blog was last updated
    def __str__(self):
        """Readable string representation of a blog post."""
        return self.youtube_title
    