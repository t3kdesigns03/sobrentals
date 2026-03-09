import os
import fnmatch

# Root directory containing all property folders
root_dir = r'E:\Ansible\sobrentals\Properties'

# String to find and replace
find_text = 'Checkout: 10:00 AM'
replace_text = 'Checkout: 11:00 AM'

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
                
                if find_text in content:
                    print(f"Match found for '{find_text}' in {filepath}")
                    new_content = content.replace(find_text, replace_text)
                    with open(filepath, 'w', encoding='utf-8') as file:
                        file.write(new_content)
                    updated_files.append(filepath)
                    print(f"Successfully updated: {filepath}")
                else:
                    print(f"No match found in {filepath}")
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