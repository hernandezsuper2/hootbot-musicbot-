"""Fun commands: .skeet and its cat facts."""
import random

import aiohttp
import discord

from .. import config
from ..config import logger, SKEET_USER_ID
from ..core import bot

@bot.command(name='skeet')
async def skeet(ctx):
    """Send a random cat fact with a cute cat image and ping skeetanese."""
    # Try to find the specific user by ID first (more reliable)
    target_user = (bot.get_user(SKEET_USER_ID) or ctx.guild.get_member(SKEET_USER_ID)) if SKEET_USER_ID else None
    
    # Fallback to name search if ID lookup fails
    if not target_user:
        search_names = ["skeetanese", "skeet"]
        
        if config.DEBUG:
            logger.info(f"Searching for user in guild with {len(ctx.guild.members)} members")
        
        for member in ctx.guild.members:
            member_display = member.display_name.lower()
            member_username = member.name.lower()
            
            for search_name in search_names:
                if (search_name in member_display or search_name in member_username or
                    member_display == search_name or member_username == search_name):
                    target_user = member
                    if config.DEBUG:
                        logger.info(f"Found user: {member.name} (display: {member.display_name}, id: {member.id})")
                    break
            
            if target_user:
                break
    
    # Get a random cat fact and image
    cat_fact = await get_random_cat_fact()
    cat_image_url = await get_random_cat_image()
    
    # 25% chance for a playful insult
    insult = ""
    if random.randint(1, 4) == 1:  # 1 in 4 chance
        playful_insults = [
            "You magnificent weirdo! 🙄",
            "Hope you're not too busy being fabulous! 💅",
            "Time to take a break from being a goofball! 🤪",
            "Stop being so extra for 5 minutes! 🙏",
            "You absolute legend (and pain in my circuits)! 🤖"
        ]
        insult = f" {random.choice(playful_insults)}"
    
    # Create embed with cat image
    embed = discord.Embed(
        title="🐱 Cat Fact Time!",
        description=cat_fact,
        color=0xFF69B4  # Hot pink color
    )
    
    if cat_image_url:
        embed.set_image(url=cat_image_url)
    
    embed.set_footer(text="Powered by adorable cats 🐾")
    
    # Send message WITHOUT pinging the user. Use display name or plain text instead.
    if target_user:
        display_name = getattr(target_user, 'display_name', None) or getattr(target_user, 'name', 'skeetanese')
        mention_text = f"{display_name}{insult} Here's your daily dose of cat wisdom! (no ping)"
    else:
        # Use plain text fallback (no mention)
        mention_text = f"Hey skeetanese{insult} Here's your daily dose of cat wisdom!"

    # Send embed with content (no mentions)
    await ctx.send(content=mention_text, embed=embed)

# ============================================================================
# HELPER FUNCTIONS - Cat Facts & Images
# ============================================================================

async def get_random_cat_fact():
    """Fetch a random cat fact from an API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://catfact.ninja/fact') as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('fact', 'Cats are amazing creatures!')
    except Exception:
        pass
    return random.choice([
        "Cats have over 20 muscles that control their ears.",
        "A group of cats is called a 'clowder'.",
        "Cats can't taste sweetness.",
        "A cat's purr vibrates at a frequency that promotes bone healing.",
        "Cats sleep for 12 to 16 hours a day.",
        "A cat has 32 muscles in each ear.",
        "Cats have a third eyelid called a 'nictitating membrane'.",
        "A cat's brain is biologically more similar to a human brain than it is to a dog's.",
        "Cats can run up to 30 mph.",
        "A cat's whiskers are roughly as wide as its body."
    ])

async def get_random_cat_image():
    """Fetch a random cute cat image from APIs."""
    image_apis = [
        'https://api.thecatapi.com/v1/images/search',
        'https://cataas.com/cat?json=true',
        'https://aws.random.cat/meow'
    ]

    async with aiohttp.ClientSession() as session:
        for api_url in image_apis:
            try:
                async with session.get(api_url, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()

                        if api_url.startswith('https://api.thecatapi.com'):
                            if data and len(data) > 0:
                                return data[0].get('url')
                        elif api_url.startswith('https://cataas.com'):
                            if data and 'url' in data:
                                return f"https://cataas.com{data['url']}"
                        elif api_url.startswith('https://aws.random.cat'):
                            if data and 'file' in data:
                                return data['file']
            except Exception as e:
                logger.debug(f"Cat image API {api_url} failed: {e}")
                continue
    
    # If all APIs fail, return a fallback image URL
    fallback_images = [
        "https://cataas.com/cat",
        "https://placekitten.com/400/300",
        "https://loremflickr.com/400/300/cat"
    ]
    return random.choice(fallback_images)
