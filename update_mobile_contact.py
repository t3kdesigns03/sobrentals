import os
import fnmatch
import re

# Root directory containing all property folders
root_dir = r'E:\Ansible\sobrentals\Properties'

# JS template to insert.
# NOTE: We avoid str.format() with braces by using simple placeholders.
js_template = """
<script>
document.addEventListener('DOMContentLoaded', function() {
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  const email = 'EMAIL_PLACEHOLDER';
  const subject = 'SUBJECT_PLACEHOLDER';
  const mailto = `mailto:${email}?subject=${encodeURIComponent(subject)}`;
  const gmail = `https://mail.google.com/mail/?view=cm&fs=1&to=${email}&su=${encodeURIComponent(subject)}`;
  const link = document.getElementById('book-link');
  if (link) {
    link.href = isMobile ? mailto : gmail;
    if (!isMobile) link.target = '_blank';
  }
});
</script>
"""

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
                
                # Find the <a> tag with the Gmail href (using &amp; or &)
                pattern = r'<a href="https://mail\.google\.com/mail/\?view=cm(&amp;|&)fs=1(&amp;|&)to=([^&]+)(&amp;|&)su=([^"]+)"'
                match = re.search(pattern, content)
                
                if match:
                    email = match.group(3)
                    subject = match.group(5).replace('%20', ' ')
                    print(f"Match found: email = '{email}', subject = '{subject}' in {filepath}")
                    
                    # Add id="book-link" if not present, and set href to #
                    # Also preserve other attributes
                    a_pattern = r'<a href="https://mail\.google\.com[^"]+"'
                    new_a = '<a id="book-link" href="#"'
                    new_content = re.sub(a_pattern, new_a, content, count=1)
                    
                    # Generate JS with extracted values
                    js_code = js_template.replace('EMAIL_PLACEHOLDER', email).replace('SUBJECT_PLACEHOLDER', subject)
                    
                    # Insert JS before </body> if not already present (check original content for id=\"book-link\")
                    if '</body>' in new_content and 'id="book-link"' not in content:
                        new_content = new_content.replace('</body>', js_code + '</body>')
                        with open(filepath, 'w', encoding='utf-8') as file:
                            file.write(new_content)
                        updated_files.append(filepath)
                        print(f"Successfully updated link and added JS in {filepath}")
                    else:
                        print(f"JS already present or no </body> found in {filepath}")
                else:
                    print(f"No matching Gmail link found in {filepath}")
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