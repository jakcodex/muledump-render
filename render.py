import argparse
from PIL import Image, ImageFilter, ImageDraw, ImageChops, ImageOps
import json
import xml
import requests
import requests_cache
from bs4 import BeautifulSoup
import untangle
import base64
import io
import random
import os


VERSION = "1.0"

# create an ArgumentParser object
parser = argparse.ArgumentParser(description='Example script for parsing command line arguments')

# add the command line arguments
parser.add_argument('--version', action='store_true', help='show version and exit')
parser.add_argument('--game-version', type=str, help='game version', default="0.0.0.0.0")
parser.add_argument('--buildhash', type=str, help='game buildhash', default="")
parser.add_argument('--dest', type=str, help='destination')
parser.add_argument('--source', type=str, help='source for file list; local path (e.g. /path/to/assets) or remote url (e.g. https://assets.muledump.com/)', default="https://assets.muledump.com")
parser.add_argument('--debug', action='store_true', help='enable debugging')

# parse the command line arguments
args = vars(parser.parse_args())
if args["source"].endswith('/'):
    args["source"] = args["source"][:-1]

# print("args", args)

# show version
if args["version"]:
    print(f"Muledump Render v{VERSION}")
    exit()

if args["dest"] is None:
    print(f"Missing required parameter: --dest")
    exit(1)

print("Muledump Render starting ...")

# clean up before we begin
if not args["debug"]:
    if os.path.exists(f"./http_cache.sqlite"):
        os.remove(f"./http_cache.sqlite")

    if os.path.exists(f"{args['dest']}/constants.js"):
        os.remove(f"{args['dest']}/constants.js")

    if os.path.exists(f"{args['dest']}/renders.png"):
        os.remove(f"{args['dest']}/renders.png")

    if os.path.exists(f"{args['dest']}/sheets.js"):
        os.remove(f"{args['dest']}/sheets.js")

# base vars
IS_LOCAL = False if args["source"].startswith("http") else True
GAME_VERSION = args["game_version"]


def add_noise(img, AMT):
    noise_img = Image.new("RGBA", img.size)
    noise_img.putdata([(int(random.random() * AMT - AMT/2), int(random.random() * AMT - AMT/2), int(random.random() * AMT - AMT/2), 0) for _ in range(img.size[0] * img.size[1])])
    img = ImageChops.add(img, noise_img)
    noise_img.putdata([(int(random.random() * AMT - AMT/2), int(random.random() * AMT - AMT/2), int(random.random() * AMT - AMT/2), 0) for _ in range(img.size[0] * img.size[1])])
    img = ImageChops.subtract(img, noise_img)
    return img


def get_concat_h_repeat(im, column):
    dst = Image.new('RGB', (im.width * column, im.height))
    for x in range(column):
        dst.paste(im, (x * im.width, 0))
    return dst


def get_concat_v_repeat(im, row):
    dst = Image.new('RGB', (im.width, im.height * row))
    for y in range(row):
        dst.paste(im, (0, y * im.height))
    return dst


def get_concat_tile_repeat(im, row, column):
    dst_h = get_concat_h_repeat(im, column)
    return get_concat_v_repeat(dst_h, row)


def argb_split(x):
    return (x & 0xFFFFFFFF).to_bytes(4, 'big')


def load_image(imagename):
    if imagename not in images:
        if IS_LOCAL:
            images[imagename] = Image.open(IMAGE_URL + imagename + ".png")
        else:
            images[imagename] = Image.open(requests.get(IMAGE_URL + imagename + ".png", stream=True).raw)
    return images[imagename]

skinfiles = set(["players"])
textilefiles = set()
petskinfiles = set()

requests_cache.install_cache(backend="sqlite")

XML_URL = args['source']
IMAGE_URL = f"{args['source']}/sheets/"

images = {}
render = Image.new("RGBA", (45 * 100 + 5, 45 * 100 + 5))
renderdraw = ImageDraw.Draw(render)
imgx = 2 #skip Empty and Unknown slots
imgy = 0
allblack = Image.new("RGBA", (40, 40), "BLACK")

items = {
     -1: ["Empty Slot", 0, -1, 5, 5, 0, 0, 0, False, 0],
      0x0: ["Unknown Item", 0, -1, 50, 5, 0, 0, 0, False, 0],
}
classes = {}
skins = {}
petAbilities = {}
textures = {}
pets = {}
petSkins = {}

render.paste(Image.open("error.png"), (50, 5))

print("+ Gathering XML")
hrefs = []
if not IS_LOCAL:
    soup = BeautifulSoup(requests.get(XML_URL+"/xml.html").content, "html.parser")
    for a in soup.find_all("a"):
        hrefs.append(a.get("href").replace("\\", "/"))
else:
    dir_path = f"{XML_URL}/xml"
    file_list = os.listdir(dir_path)
    hrefs = [f"xml/{f}" for f in file_list if os.path.isfile(os.path.join(dir_path, f))]

# print("hrefs", hrefs)

print("+ Processing XML")
for href in hrefs:
    if href is not None:
        try:
            if IS_LOCAL:
                with open(XML_URL + "/" + href, "r") as f:
                    xmldata = f.read()
            else:
                xmldata = requests.get(XML_URL + "/" + href).content.decode("utf-8")
            data = untangle.parse(xmldata)
        except xml.sax._exceptions.SAXParseException:
            continue
        datatype = dir(data)[0]
        if datatype == "Objects" and "Object" in dir(data.Objects):
            for obj in data.Objects.Object:
                if "Class" not in dir(obj):
                    continue
                clazz = None
                if isinstance(obj.Class, list):
                    clazz = obj.Class[0]
                else:
                    clazz = obj.Class
                if clazz.cdata == "Player":
                    baseStats = [
                        int(obj.MaxHitPoints.cdata),
                        int(obj.MaxMagicPoints.cdata),
                        int(obj.Attack.cdata),
                        int(obj.Defense.cdata),
                        int(obj.Speed.cdata),
                        int(obj.Dexterity.cdata),
                        int(obj.HpRegen.cdata),
                        int(obj.MpRegen.cdata),
                    ]
                    averages = {}
                    for f in obj.LevelIncrease:
                        averages[f.cdata] = (int(f["min"]) + int(f["max"])) / 2 * 19
                    avgs = [
                        averages["MaxHitPoints"],
                        averages["MaxMagicPoints"],
                        averages["Attack"],
                        averages["Defense"],
                        averages["Speed"],
                        averages["Dexterity"],
                        averages["HpRegen"],
                        averages["MpRegen"],
                    ]
                    avgs = [x+y for x,y in zip(baseStats, avgs)]
                    if obj["type"].startswith("0x"):
                        key = int(obj["type"][2:], 16)
                    else:
                        1/0
                    classes[key] = [
                        obj["id"],
                        baseStats,
                        avgs,
                        [
                            int(obj.MaxHitPoints["max"]),
                            int(obj.MaxMagicPoints["max"]),
                            int(obj.Attack["max"]),
                            int(obj.Defense["max"]),
                            int(obj.Speed["max"]),
                            int(obj.Dexterity["max"]),
                            int(obj.HpRegen["max"]),
                            int(obj.MpRegen["max"]),
                        ],
                        [int(x) for x in obj.SlotTypes.cdata.split(",")[:4]]
                    ]
                    if obj.AnimatedTexture.Index.cdata.startswith('0x'):
                        index = int(obj.AnimatedTexture.Index.cdata[2:], 16)
                    else:
                        index = int(obj.AnimatedTexture.Index.cdata)
                    skins[key] = [
                        obj["id"],
                        index,
                        False,
                        obj.AnimatedTexture.File.cdata,
                        key,
                    ]
                if clazz.cdata == "Skin" or "Skin" in dir(obj):
                    if not obj.PlayerClassType.cdata.startswith('0x'):
                        1/0
                    if not obj["type"].startswith('0x'):
                        1/0
                    if obj.AnimatedTexture.Index.cdata.startswith('0x'):
                        index = int(obj.AnimatedTexture.Index.cdata[2:], 16)
                    else:
                        index = int(obj.AnimatedTexture.Index.cdata)
                    skins[int(obj["type"][2:], 16)] = [
                        obj["id"],
                        index,
                        "16" in obj.AnimatedTexture.File.cdata,
                        obj.AnimatedTexture.File.cdata,
                        int(obj.PlayerClassType.cdata[2:], 16)
                    ]
                    skinfiles.add(obj.AnimatedTexture.File.cdata)
                elif clazz.cdata == "PetAbility" or "PetAbility" in dir(obj):
                    if obj["type"].startswith("0x"):
                        petAbilities[int(obj["type"][2:], 16)] = obj["id"]
                    else:
                        1/0
                if clazz.cdata == "Dye":
                    if "Tex1" in dir(obj):
                        key = obj.Tex1.cdata
                        offs = 0
                    elif "Tex2" in dir(obj):
                        key = obj.Tex2.cdata
                        offs = 2
                    else:
                        1/0
                    if key.startswith("0x"):
                        key = int(key[2:], 16)
                    else:
                        1/0 #key = int(key)
                    data = textures.get(key, [None]*4)
                    data[offs+0] = obj["id"]
                    if obj["type"].startswith("0x"):
                        data[offs+1] = int(obj["type"][2:], 16)
                    else:
                        1/0
                    textures[key] = data
                if clazz.cdata == "Equipment" or clazz.cdata == "Dye":
                    if "BagType" not in dir(obj):
                        # Procs are Equipment too for some reason!??
                        # but also there are items without bags? e.g. Beer Slurp
                        BagType = 0
                    else:
                        BagType = int(obj.BagType.cdata)
                    if "DisplayId" in dir(obj) and clazz.cdata != "Dye":
                        if isinstance(obj.DisplayId, list):
                            id = obj.DisplayId[0].cdata
                        else:
                            id = obj.DisplayId.cdata
                    else:
                        id = obj["id"]
                    #print(id)
                    type = obj["type"]
                    if type.startswith("0x"):
                        type = int(type[2:], 16)
                    else:
                        type = int(type)
                    if "Tier" in dir(obj):
                        tier = int(obj.Tier.cdata)
                    else:
                        tier = -1
                    if "XPBonus" in dir(obj):
                        xp = int(obj.XPBonus.cdata)
                    else:
                        xp = 0
                    if "feedPower" in dir(obj):
                        fp = int(obj.feedPower.cdata)
                    else:
                        fp = 0
                    if isinstance(obj.SlotType, list):
                        slot = int(obj.SlotType[0].cdata)
                    else:
                        slot = int(obj.SlotType.cdata)
                    soulbound = "Soulbound" in dir(obj)
                    utst = 0
                    if "setName" in repr(obj):
                        utst = 2
                    elif (slot >= 1 and slot <= 9) or (slot >= 11 and slot <= 25):
                        if soulbound and tier == -1:
                            utst = 1

                    if "Texture" in dir(obj):
                        imagename = obj.Texture.File.cdata
                        imageindex = obj.Texture.Index.cdata
                    else:
                        imagename = obj.AnimatedTexture.File.cdata
                        imageindex = obj.AnimatedTexture.Index.cdata
                    if imageindex.startswith("0x"):
                        imageindex = int(imageindex[2:], 16)
                    else:
                        imageindex = int(imageindex)
                    # checking whether imageindex is hex or decimal is usually pretty good at telling normalIndex, but some items are wrong!
                    normalIndex = imagename not in ["oryxSanctuaryChars32x32", "chars8x8dEncounters", "chars8x8rPets1", "chars16x16dEncounters2", "playerskins", "petsDivine", "epicHiveChars16x16", "playerskins16"]
                    img = load_image(imagename)

                    # TODO: manifest.xml has this data, but this seems alright for now
                    imgTileSize = 8
                    if "16" in imagename or imagename == "petsDivine":
                        imgTileSize = 16
                    elif "32" in imagename:
                        imgTileSize = 32

                    if normalIndex:
                        srcw = img.size[0] / imgTileSize
                        srcx = imgTileSize * (imageindex % srcw)
                        srcy = imgTileSize * (imageindex // srcw)
                    elif imagename == "playerskins":
                        srcx = 0
                        srcy = 3 * imgTileSize * imageindex
                    else:
                        srcx = 0
                        srcy = imgTileSize * imageindex

                    icon = img.crop((srcx, srcy, srcx+imgTileSize, srcy+imgTileSize)).resize((32, 32), Image.NEAREST)
                    icon = ImageOps.expand(icon, 4)
                    #icon = add_noise(icon, 20)
                    edges = icon.split()[-1].filter(ImageFilter.MaxFilter(3))
                    shadow = edges.filter(ImageFilter.BoxBlur(7)).point(lambda alpha: alpha // 2)
                    render.paste(allblack, (imgx * 45 + 5, imgy * 45 + 5), shadow)
                    render.paste(allblack, (imgx * 45 + 5, imgy * 45 + 5), edges)
                    icon = icon.crop((1, 1, 39, 39))
                    render.paste(icon, (imgx * 45 + 5 + 1, imgy * 45 + 5 + 1), icon)

                    if "Mask" in dir(obj):
                        maskname = obj.Mask.File.cdata
                        maskindex = obj.Mask.Index.cdata
                        if maskindex.startswith("0x"):
                            maskindex = int(maskindex[2:], 16)
                        else:
                            print(href,id)
                            1/0
                        img = load_image(maskname)
                        srcw = img.size[0] / imgTileSize
                        srcx = imgTileSize * (maskindex % srcw)
                        srcy = imgTileSize * (maskindex // srcw)
                        mask = img.crop((srcx, srcy, srcx+imgTileSize, srcy+imgTileSize)).resize((32, 32), Image.NEAREST)
                        mask = ImageOps.expand(mask, 4)
                        if "Tex1" in dir(obj) and "Tex2" in dir(obj):
                            print(href,id)
                            1/0
                        elif "Tex1" in dir(obj):
                            tex = obj.Tex1.cdata
                        elif "Tex2" in dir(obj):
                            tex = obj.Tex2.cdata
                        else:
                            print(href,id)
                            1/0
                        if tex.startswith("0x"):
                            tex = int(tex[2:], 16)
                        else:
                            print(href,id)
                            1/0
                        a,r,g,b = argb_split(tex)
                        if a == 1: #color
                            img = Image.new("RGB", (40, 40), (r,g,b))
                        else: #texture
                            if r > 0 or g > 0:
                                print("invalid texture, would crash:", href,id)
                                print("continuing with error.png instead.")
                                img = Image.open("error.png")
                            else:
                                textilefiles.add(a)
                                img = load_image(f"textile{a}x{a}")
                                srcw = img.size[0] / a
                                srcx = a * (b % srcw)
                                srcy = a * (b // srcw)
                                img = img.crop((srcx, srcy, srcx+a, srcy+a))
                                img = get_concat_tile_repeat(img, 10, 10)
                                img = img.crop((0, 0, 32, 32))
                                img = ImageOps.expand(img, 4)
                        render.paste(allblack, (imgx * 45 + 5, imgy * 45 + 5), mask)
                        render.paste(img, (imgx * 45 + 5, imgy * 45 + 5), mask.split()[0])
                        render.paste(img, (imgx * 45 + 5, imgy * 45 + 5), mask.split()[1])

                    if "Quantity" in dir(obj):
                        num = obj.Quantity.cdata
                        renderdraw.text((imgx * 45 + 5 + 3 - 1, imgy * 45 + 5 + 3 - 1), num, fill="#000")
                        renderdraw.text((imgx * 45 + 5 + 3 - 1, imgy * 45 + 5 + 3 - 0), num, fill="#000")
                        renderdraw.text((imgx * 45 + 5 + 3 - 1, imgy * 45 + 5 + 3 + 1), num, fill="#000")
                        renderdraw.text((imgx * 45 + 5 + 3 - 0, imgy * 45 + 5 + 3 - 1), num, fill="#000")
                        renderdraw.text((imgx * 45 + 5 + 3 - 0, imgy * 45 + 5 + 3 + 1), num, fill="#000")
                        renderdraw.text((imgx * 45 + 5 + 3 + 1, imgy * 45 + 5 + 3 - 1), num, fill="#000")
                        renderdraw.text((imgx * 45 + 5 + 3 + 1, imgy * 45 + 5 + 3 - 0), num, fill="#000")
                        renderdraw.text((imgx * 45 + 5 + 3 + 1, imgy * 45 + 5 + 3 + 1), num, fill="#000")
                        renderdraw.text((imgx * 45 + 5 + 3 - 0, imgy * 45 + 5 + 3 - 0), num, fill="#fff")

                    items[type] = [id, slot, tier, imgx * 45 + 5, imgy * 45 + 5, xp, fp, BagType, soulbound, utst]
                    imgx += 1
                    if imgx >= 100:
                        imgx = 0
                        imgy += 1
                        if imgy >= 100:
                            1/0

                if clazz.cdata == "Pet":
                    petid = obj["type"]
                    if petid.startswith("0x"):
                        petid = petid[2:]
                    petid = int(petid, 16)
                    pets[petid] = {
                        "id": obj["id"]
                    }
                    for key in ["Family", "Rarity", "DefaultSkin", "Size"]:
                        pets[petid][key] = None if getattr(obj, key, None) is None else getattr(obj, key).cdata.replace('\n', '').strip()
                        if key == "Size":
                            pets[petid][key] = int(pets[petid][key])
                        if pets[petid][key] == "":
                            pets[petid][key] = None

                if clazz.cdata == "PetSkin":
                    petskinid = obj["type"]
                    if petskinid.startswith("0x"):
                        petskinid = petskinid[2:]
                    petskinid = int(petskinid, 16)
                    petSkins[petskinid] = {
                        "id": obj["id"]
                    }
                    for key in ["DisplayId", "ItemTier", "Family", "Rarity"]:
                        petSkins[petskinid][key] = None if getattr(obj, key, None) is None else getattr(obj, key).cdata.replace('\n', '').strip()
                        if key == "ItemTier" and petSkins[petskinid][key] is not None:
                            petSkins[petskinid][key] = int(petSkins[petskinid][key])
                        if petSkins[petskinid][key] == "":
                            petSkins[petskinid][key] = None

                    if obj.AnimatedTexture.Index.cdata.startswith('0x'):
                        index = int(obj.AnimatedTexture.Index.cdata[2:], 16)
                    else:
                        index = int(obj.AnimatedTexture.Index.cdata)
                    petSkins[petskinid]["index"] = index
                    petSkins[petskinid]["16"] = "16" in obj.AnimatedTexture.File.cdata
                    petSkins[petskinid]["AnimatedTexture"] = obj.AnimatedTexture.File.cdata
                    petskinfiles.add(obj.AnimatedTexture.File.cdata)

render = render.crop((0, 0, 45 * 100 + 5, 45 * (imgy + 1) + 5))

from datetime import datetime
now = datetime.now().strftime("%Y%m%d-%H%M%S")

print("+ Writing constants.js")
with open(f"{args['dest']}/constants.js", "w") as fh:
    fh.write("//  Generated with https://github.com/jakcodex/muledump-render\n")
    fh.write(f"//  Realm of the Mad God v{GAME_VERSION}")
    if args["buildhash"]:
        fh.write(f" (build: {args['buildhash']})")
    fh.write(f"\n\n")
    fh.write(f'rendersVersion = "renders-{now}-{GAME_VERSION}";\n\n')
    fh.write('//   type: ["id", SlotType, Tier, x, y, FameBonus, feedPower, BagType, Soulbound, UT/ST],\n')
    fh.write("items = {\n")
    for itemid, itemdata in sorted(items.items()):
        if itemid == -1:
            fh.write(f"  '{itemid}': {itemdata},\n".replace("False,", "false,").replace("True,", "true,"))
        else:
            fh.write(f"  {itemid}: {itemdata},\n".replace("False,", "false,").replace("True,", "true,"))
    fh.write("};\n\n")
    fh.write('//   type: ["id", base, averages, maxes, slots]\n')
    fh.write("classes = {\n")
    for classid, classdata in sorted(classes.items()):
        fh.write(f"  {classid}: {classdata},\n")
    fh.write("};\n\n")
    fh.write('//   type: ["id", index, 16x16, "sheet", class]\n')
    fh.write("skins = {\n")
    for skinid, skindata in sorted(skins.items()):
        fh.write(f"  {skinid}: {skindata},\n".replace("False,", "false,").replace("True,", "true,"))
    fh.write("};\n\n")
    fh.write('//   type: "id"\n')
    fh.write("petAbilities = {\n")
    for petAbilId, petAbilName in sorted(petAbilities.items()):
        fh.write(f'  {petAbilId}: "{petAbilName}",\n')
    fh.write("};\n\n")
    fh.write('//   texId: ["clothing id", clothing type, "accessory id", accessory type]\n')
    fh.write("textures = {\n")
    for textureId, textureData in sorted(textures.items()):
        fh.write(f"  {textureId}: {textureData},\n")
    fh.write("}\n\n")
    fh.write('//  type: ["id", "Family", "Rarity", "DefaultSkin", "Size"]\n')
    fh.write("pets = {\n")
    for petid, petdata in sorted(pets.items()):
        petdata = list(petdata.values())
        petdata = json.dumps(petdata)
        fh.write(f"  {petid}: {petdata},\n")
    fh.write("};\n\n")
    fh.write('//  type: ["id", "DisplayId", "ItemTier", "Family", "Rarity"]\n')
    fh.write("petSkins = {\n")
    for petskinid, petskindata in sorted(petSkins.items()):
        petskindata = list(petskindata.values())
        petskindata = json.dumps(petskindata)
        fh.write(f"  {petskinid}: {petskindata},\n")
    fh.write("};\n")

print("+ Writing renders.png")
render.save(f"{args['dest']}/renders.png", "PNG", quality=100)

print("+ Writing sheets.js")
with open(f"{args['dest']}/sheets.js", "w") as fh:

    # textiles
    fh.write("textiles = {\n")
    for textilefile in sorted(textilefiles):
        if IS_LOCAL:
            with open(IMAGE_URL + f"textile{textilefile}x{textilefile}.png", 'rb') as f:
                textiledata = base64.b64encode(f.read()).decode()
        else:
            textiledata = base64.b64encode(requests.get(IMAGE_URL + f"textile{textilefile}x{textilefile}.png").content).decode()
        fh.write(f"  {textilefile}: 'data:image/png;base64,{textiledata}',\n")
    fh.write("};\n\n")

    # player skins
    fh.write("skinsheets = {\n")
    for skinfile in sorted(skinfiles):

        if IS_LOCAL:
            with open(IMAGE_URL + skinfile + ".png", 'rb') as f:
                skindata = base64.b64encode(f.read()).decode()
        else:
            skindata = base64.b64encode(requests.get(IMAGE_URL + skinfile + ".png").content).decode()

        fh.write(f"  {skinfile}: 'data:image/png;base64,{skindata}',\n")

        if IS_LOCAL:
            with open(IMAGE_URL + skinfile + "_mask.png", 'rb') as f:
                skindata = base64.b64encode(f.read()).decode()
        else:
            skindata = base64.b64encode(requests.get(IMAGE_URL + skinfile + "_mask.png").content).decode()

        fh.write(f"  {skinfile}Mask: 'data:image/png;base64,{skindata}',\n")
    fh.write("};\n\n")

    # pet skins
    fh.write("petskinsheets = {\n")
    for petskinfile in sorted(petskinfiles):

        if IS_LOCAL:
            with open(IMAGE_URL + petskinfile + ".png", 'rb') as f:
                petskindata = base64.b64encode(f.read()).decode()
        else:
            petskindata = base64.b64encode(requests.get(IMAGE_URL + petskinfile + ".png").content).decode()

        fh.write(f"  {petskinfile}: 'data:image/png;base64,{petskindata}',\n")

    fh.write("};\n\n")

    # save renders
    buf = io.BytesIO()
    render.save(buf, "PNG", quality=100)
    renderdata = base64.b64encode(buf.getvalue()).decode()
    fh.write(f"renders = 'data:image/png;base64,{renderdata}';\n")

print("")
