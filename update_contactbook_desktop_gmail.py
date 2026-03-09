import os
import fnmatch
import re

# Root directory containing all property folders
root_dir = r'E:\Ansible\sobrentals\Properties'

# Function to update files
def update_html_files(directory):
    updated_files = []
    print(f"Starting scan in directory: {directory}")
    for root, dirs, files in os.walk(directory):
        print(f"Scanning folder: {root}")
        print(f"Found {len(files)} files, {len(dirs)} subdirs")
        html_files = fnmatch.filter(files, '*.html')
        print(f"Found {len(html_files)} HTML files in this folder")
        for filename in html_files:
            filepath = os.path.join(root, filename)
            print(f"Processing file: {filepath}")
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    content = file.read()
                print(f"File size: {len(content)} characters")
                
                # Regex pattern to find the mailto href
                pattern = r'<a href="mailto:sobrentals@yahoo\.com\?subject=([^"]+)"'
                match = re.search(pattern, content)
                
                if match:
                    subject = match.group(1)
                    print(f"Match found: Original subject = '{subject}' in {filepath}")
                    new_href = f'https://mail.google.com/mail/?view=cm&fs=1&to=sobrentals@yahoo.com&su={subject}'
                    # Replace the entire href attribute value
                    new_content = re.sub(pattern, f'<a href="{new_href}"', content)
                    with open(filepath, 'w', encoding='utf-8') as file:
                        file.write(new_content)
                    updated_files.append(filepath)
                    print(f"Successfully updated to new href: '{new_href}' in {filepath}")
                else:
                    print(f"No matching mailto link found in {filepath}")
            except Exception as e:
                print(f"Error processing {filepath}: {str(e)}")
    
    if updated_files:
        print(f"\nSuccessfully updated {len(updated_files)} files.")
        print("Updated files list:")
        for f in updated_files:
            print(f" - {f}")
    else:
        print("No files needed updating.")

# Run the update
update_html_files(root_dir)