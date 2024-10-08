from functools import reduce

import os

import puremagic
from django.core.exceptions import ImproperlyConfigured

from .settings import (
    IMAGE_SETS,
    JPEG_QUAL,
    VERSATILEIMAGEFIELD_POST_PROCESSOR,
    VERSATILEIMAGEFIELD_SIZED_DIRNAME,
    VERSATILEIMAGEFIELD_FILTERED_DIRNAME,
    WEBP_QUAL,
)

# PIL-supported file formats as found here:
# https://infohost.nmt.edu/tcc/help/pubs/pil/formats.html
# {mime type: PIL Identifier}
MIME_TYPE_TO_PIL_IDENTIFIER = {
    'image/x-ms-bmp': 'BMP',
    'image/bmp': 'BMP',
    'image/dcx': 'DCX',
    'image/eps': 'eps',
    'image/gif': 'GIF',
    'image/jpeg': 'JPEG',
    'image/pcd': 'PCD',
    'image/pcx': 'PCX',
    'application/pdf': 'PDF',
    'image/png': 'PNG',
    'image/x-ppm': 'PPM',
    'image/psd': 'PSD',
    'image/tiff': 'TIFF',
    'image/x-xbitmap': 'XBM',
    'image/x-xpm': 'XPM',
    'image/webp': 'WEBP',
}


class InvalidSizeKeySet(Exception):
    pass


class InvalidSizeKey(Exception):
    pass


def post_process_image_key(image_key):
    """Apply the processor function associated with settings.VER"""
    if VERSATILEIMAGEFIELD_POST_PROCESSOR is None:
        return image_key
    else:
        return VERSATILEIMAGEFIELD_POST_PROCESSOR(image_key)


def get_resized_filename(filename, width, height, filename_key):
    """
    Return the 'resized filename' (according to `width`, `height` and
    `filename_key`) in the following format:
    `filename`-`filename_key`-`width`x`height`.ext
    """
    try:
        image_name, ext = filename.rsplit('.', 1)
    except ValueError:
        image_name = filename
        ext = 'jpg'

    resized_template = "%(filename_key)s-%(width)dx%(height)d"
    quality = WEBP_QUAL if ext.lower() == 'webp' else JPEG_QUAL
    if ext.lower() in ['jpg', 'jpeg', 'webp']:
        resized_template = resized_template + "-%(quality)d"

    resized_key = resized_template % ({
        'filename_key': filename_key,
        'width': width,
        'height': height,
        'quality': quality
    })

    return "%(image_name)s-%(image_key)s.%(ext)s" % ({
        'image_name': image_name,
        'image_key': post_process_image_key(resized_key),
        'ext': ext
    })


def get_resized_path(path_to_image, width, height,
                     filename_key, storage):
    """
    Return a `path_to_image` location on `storage` as dictated by `width`, `height`
    and `filename_key`
    """
    containing_folder, filename = os.path.split(path_to_image)

    resized_filename = get_resized_filename(
        filename,
        width,
        height,
        filename_key
    )

    joined_path = os.path.join(*[
        VERSATILEIMAGEFIELD_SIZED_DIRNAME,
        containing_folder,
        resized_filename
    ]).replace(' ', '')  # Removing spaces so this path is memcached friendly

    return joined_path


def get_filtered_filename(filename, filename_key):
    """
    Return the 'filtered filename' (according to `filename_key`)
    in the following format:
    `filename`__`filename_key`__.ext
    """
    try:
        image_name, ext = filename.rsplit('.', 1)
    except ValueError:
        image_name = filename
        ext = 'jpg'
    return "%(image_name)s__%(filename_key)s__.%(ext)s" % ({
        'image_name': image_name,
        'filename_key': filename_key,
        'ext': ext
    })


def get_filtered_path(path_to_image, filename_key, storage):
    """
    Return the 'filtered path'
    """
    containing_folder, filename = os.path.split(path_to_image)

    filtered_filename = get_filtered_filename(filename, filename_key)
    path_to_return = os.path.join(*[
        containing_folder,
        VERSATILEIMAGEFIELD_FILTERED_DIRNAME,
        filtered_filename
    ])
    # Removing spaces so this path is memcached key friendly
    path_to_return = path_to_return.replace(' ', '')
    return path_to_return


def get_image_metadata_from_file(file_like):
    """
    Receive a valid image file and returns a 2-tuple of two strings:
        [0]: Image format (i.e. 'jpg', 'gif' or 'png')
        [1]: InMemoryUploadedFile-friendly save format (i.e. 'image/jpeg')
    image_format, in_memory_file_type
    """
    mime_type = puremagic.magic_stream(file_like)

    if mime_type and len(mime_type) > 0:
        mime_type = mime_type[0].mime_type
    else:
        mime_type = ''

    file_like.seek(0)
    image_format = MIME_TYPE_TO_PIL_IDENTIFIER[mime_type]
    return image_format, mime_type


def validate_versatileimagefield_sizekey_list(sizes):
    """
    Validate a list of size keys.

    `sizes`: An iterable of 2-tuples, both strings. Example:
    [
        ('large', 'url'),
        ('medium', 'crop__400x400'),
        ('small', 'thumbnail__100x100')
    ]
    """
    try:
        for key, size_key in sizes:
            size_key_split = size_key.split('__')
            if size_key_split[-1] != 'url' and (
                'x' not in size_key_split[-1]
            ):
                raise InvalidSizeKey(
                    "{0} is an invalid size. All sizes must be either "
                    "'url' or made up of at least two segments separated "
                    "by double underscores. Examples: 'crop__400x400', "
                    "filters__invert__url".format(size_key)
                )
    except ValueError:
        raise InvalidSizeKeySet(
            '{} is an invalid size key set. Size key sets must be an '
            'iterable of 2-tuples'.format(str(sizes))
        )
    return list(set(sizes))


def get_url_from_image_key(image_instance, image_key):
    """Build a URL from `image_key`."""
    img_key_split = image_key.split('__')
    if 'x' in img_key_split[-1]:
        size_key = img_key_split.pop(-1)
    else:
        size_key = None
    img_url = reduce(getattr, img_key_split, image_instance)
    if size_key:
        img_url = img_url[size_key].url
    return img_url


def build_versatileimagefield_url_set(image_instance, size_set, request=None):
    """
    Return a dictionary of urls corresponding to size_set
    - `image_instance`: A VersatileImageFieldFile
    - `size_set`: An iterable of 2-tuples, both strings. Example:
        [
            ('large', 'url'),
            ('medium', 'crop__400x400'),
            ('small', 'thumbnail__100x100')
        ]

        The above would lead to the following response:
        {
            'large': 'http://some.url/image.jpg',
            'medium': 'http://some.url/__sized__/image-crop-400x400.jpg',
            'small': 'http://some.url/__sized__/image-thumbnail-100x100.jpg',
        }
    - `request`:
    """
    size_set = validate_versatileimagefield_sizekey_list(size_set)
    to_return = {}
    if image_instance or image_instance.field.placeholder_image:
        for key, image_key in size_set:
            img_url = get_url_from_image_key(image_instance, image_key)
            if request is not None:
                img_url = request.build_absolute_uri(img_url)
            to_return[key] = img_url
    return to_return


def get_rendition_key_set(key):
    """
    Retrieve a validated and prepped Rendition Key Set from
    settings.VERSATILEIMAGEFIELD_RENDITION_KEY_SETS
    """
    try:
        rendition_key_set = IMAGE_SETS[key]
    except KeyError:
        raise ImproperlyConfigured(
            "No Rendition Key Set exists at "
            "settings.VERSATILEIMAGEFIELD_RENDITION_KEY_SETS['{}']".format(key)
        )
    else:
        return validate_versatileimagefield_sizekey_list(rendition_key_set)
