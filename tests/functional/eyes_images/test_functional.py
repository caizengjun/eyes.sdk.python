# from applitools.core import Region, UnscaledFixedCutProvider
from os import path

from applitools.images import Region, Target
from PIL import Image

here = path.abspath(path.dirname(__file__))


def test_check_image(eyes):
    eyes.open("images", "TestCheckImage", dimension=dict(width=100, height=400))
    eyes.check_image(path.join(here, "resources/minions-800x500.jpg"))
    eyes.close()


def test_check_image_path_fluent(eyes):
    eyes.open("images", "TestCheckImage_Fluent")
    eyes.check(
        "TestCheckImage_Fluent",
        Target().image(path.join(here, "resources/minions-800x500.jpg")),
    )
    eyes.close()


def test_check_raw_image_fluent(eyes):
    eyes.open("images", "TestCheckImage_Fluent")
    eyes.check("TestCheckImage_Fluent", Target().image(Image.new("RGBA", (600, 600))))
    eyes.close()


def test_check_image_with_ignore_region_fluent(eyes):
    eyes.open("images", "TestCheckImageWithIgnoreRegion_Fluent")
    eyes.check(
        "TestCheckImage_WithIgnoreRegion_Fluent",
        Target()
        .image(path.join(here, "resources/minions-800x500.jpg"))
        .ignore(Region(10, 20, 30, 40)),
    )
    eyes.close()


# def test_check_image_fluent_cut_provider(eyes):
#     eyes.image_cut = UnscaledFixedCutProvider(200, 100, 100, 50)
#     eyes.check("TestCheckImage_Fluent", Target.image("resources/minions-800x500.jpg"))
#     eyes.close()
