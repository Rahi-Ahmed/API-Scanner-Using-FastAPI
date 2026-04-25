from bs4 import BeautifulSoup

def process_html():
    html_doc = """<div class="main"><img src="icon.png" /><b>Hello</b></div>"""
    soup = BeautifulSoup(html_doc, 'html.parser')
    
    div_tag = soup.find('div')
    img_tag = soup.find('img')
    
    if div_tag.has_key('class'):
        print("Found class attribute")

    if img_tag.isSelfClosing():
        print("Image is self closing")

    print("Iterating next elements:")
    for element in div_tag.nextGenerator():
        if element.name:
            print(element.name)

if __name__ == "__main__":
    process_html()