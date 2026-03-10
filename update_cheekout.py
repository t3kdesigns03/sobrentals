import os
import re

# Base directory
base_dir = r'E:\Ansible\sobrentals\Properties'

# Pattern for removing (reviews) next to rating - flexible for spaces, ★, numbers
remove_pattern = re.compile(r'(\d\.\d(?:\s*★)?)\s*\(\s*(?:\d+\s*)?reviews?\s*\)', re.IGNORECASE)

# Standalone "(50 reviews)" or " (50 reviews)" in any tag (remove the phrase)
standalone_reviews_pattern = re.compile(r'\s*\(\s*50\s+reviews?\s*\)', re.IGNORECASE)

# Change 4.9 to 5.0 in rating contexts (after we've stripped (reviews))
rating_49_to_50_patterns = [
    (re.compile(r'4\.9\s*★'), '5.0 ★'),   # "4.9 ★" -> "5.0 ★"
    (re.compile(r'>4\.9<'), '>5.0<'),       # ">4.9<" e.g. in <span>4.9</span> or <p>4.9</p>
]

# Patterns for inserting missing rating (using negative lookahead to check if rating <p> is absent)
# For properties.html (list pages): Insert after <p>Sleeps X</p> if no <p>\d.\d</p> follows immediately
list_insert_pattern = re.compile(r'(<p>Sleeps \d+</p>)\s*(?!<p>\d\.\d(?:\s*★)?</p>)', re.IGNORECASE | re.DOTALL | re.MULTILINE)

# For individual detail pages: Insert after <p>X Bathrooms</p> if no <p>\d.\d ★</p> follows immediately
detail_insert_pattern = re.compile(r'(<p>\d+ Bathrooms?</p>)\s*(?!<p>\d\.\d\s*★?</p>)', re.IGNORECASE | re.DOTALL | re.MULTILINE)

# Traverse each location folder
for location in os.listdir(base_dir):
    loc_dir = os.path.join(base_dir, location)
    if not os.path.isdir(loc_dir):
        continue
    
    print(f"Processing folder: {location}")
    
    # Process all .html files in the folder
    for filename in os.listdir(loc_dir):
        if not filename.endswith('.html'):
            continue
        
        filepath = os.path.join(loc_dir, filename)
        print(f"  Checking file: {filename}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Step 1: Remove any (reviews) inline with ratings
        new_content = remove_pattern.sub(r'\1', html_content)
        
        # Step 2: Remove standalone "(50 reviews)" text (e.g. in separate spans)
        new_content = standalone_reviews_pattern.sub('', new_content)
        
        # Step 3: Change 4.9 to 5.0 in rating contexts
        for pat, repl in rating_49_to_50_patterns:
            new_content = pat.sub(repl, new_content)
        
        # Step 4: Insert missing ratings based on file type
        if filename == 'properties.html':
            # For list pages: Insert "5.0" if missing after Sleeps
            new_content = list_insert_pattern.sub(r'\1\n<p>5.0</p>', new_content)
        else:
            # For detail pages: Insert "5.0 ★" if missing after Bathrooms
            new_content = detail_insert_pattern.sub(r'\1\n<p>5.0 ★</p>', new_content)
        
        if new_content != html_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"    Updated: Processed ratings (removals/insertions) in {filename}")
        else:
            print(f"    No changes needed in {filename}")
    
print("Processing complete for all locations.")