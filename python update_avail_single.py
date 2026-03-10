import os
import re

# Directory containing the HTML files for Sheila's properties
directory = r'E:\Ansible\sobrentals\Properties\Ledges'

# Iterate over each file in the directory
for filename in os.listdir(directory):
    if filename.endswith('.html'):
        filepath = os.path.join(directory, filename)
        
        # Read the file content
        with open(filepath, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Use regex to replace "4.9 ★ (…reviews…)" with "5.0 ★"
        # This handles variations like "(50 reviews)", "(1 review)", or "(reviews)"
        new_content = re.sub(r'4\.9 ★ \([^)]*\)', '5.0 ★', content)
        
        # If changes were made, write back to the file
        if new_content != content:
            with open(filepath, 'w', encoding='utf-8') as file:
                file.write(new_content)
            print(f'Updated rating in {filename} for Sheila\'s property management.')
        else:
            print(f'No changes needed in {filename}.')