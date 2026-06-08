from django import template

register = template.Library()

_DEST_URLS = {
    "albania.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/55/Tirana_panorama_%287246584338%29.jpg/960px-Tirana_panorama_%287246584338%29.jpg",
    "georgia.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/20110421_Tbilisi_Georgia_Panoramic.jpg/960px-20110421_Tbilisi_Georgia_Panoramic.jpg",
    "srilanka.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/07/Colombo_Skyline_Jan_2022.jpg/960px-Colombo_Skyline_Jan_2022.jpg",
    "nmacedonia.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/99/Skopje_2014.jpg/960px-Skopje_2014.jpg",
    "kosovo.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/65/PrishtinaKosovoSkyline.JPG/960px-PrishtinaKosovoSkyline.JPG",
    "japan.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/98/Kappabashi-dori_streetcorner_%28Kitchen_town_-_southern_end%29_a_sunny_morning_in_Tokyo_Japan.jpg/960px-Kappabashi-dori_streetcorner_%28Kitchen_town_-_southern_end%29_a_sunny_morning_in_Tokyo_Japan.jpg",
    "morocco.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d0/Oriental_hanging_lanterns._Souk_Haddadine%2C_Marrakech_Medina%2C_Morocco.jpg/960px-Oriental_hanging_lanterns._Souk_Haddadine%2C_Marrakech_Medina%2C_Morocco.jpg",
    "portugal.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/View_of_Lisbon_and_azulejo_panel%2C_S%C3%A3o_Pedro_de_Alc%C3%A2ntara_viewpoint%2C_Lisbon%2C_Portugal_julesvernex2.jpg/960px-View_of_Lisbon_and_azulejo_panel%2C_S%C3%A3o_Pedro_de_Alc%C3%A2ntara_viewpoint%2C_Lisbon%2C_Portugal_julesvernex2.jpg",
    "vietnam.png": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/20/Sunset_over_Hanoi_After_the_Rain.jpg/960px-Sunset_over_Hanoi_After_the_Rain.jpg",
}


@register.filter
def dest_img_url(image_file):
    return _DEST_URLS.get(image_file, "")
