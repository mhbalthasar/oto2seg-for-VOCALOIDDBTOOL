from __future__ import annotations
import json
import re
from os import path
from typing import Optional, TypedDict
from wave import open as open_wave

from phoneme import *

class OtoInfo:
    wav_file: str
    alias: str
    offset: float
    consonant: float
    cutoff: float
    preutterance: float
    overlap: float

class JPhonemeMapItem(TypedDict):
    kana: str
    romaji: str
    phoneme: list[str]
    type: str

class OtoEntryPhonemeInfo:
    type: str
    phoneme_info_list: list[JPhonemeMapItem]
    phoneme_list: list[str]
    is_alternative: bool

def read_oto(oto_file: str) -> dict[str, list[OtoInfo]]:
    """Reads an oto.ini file and returns a dictionary of lists of OtoInfo objects."""
    oto_dict: dict[str, list[OtoInfo]] = {}
    oto_path = path.dirname(oto_file)
    with open(oto_file, 'r', encoding="shift-jis") as f:
        for line in f:
            line = line.strip()
            if line == "" or line.startswith("#") or line.startswith(";"):
                continue
            
            wav_file, oto_params = line.split("=")

            if wav_file not in oto_dict:
                oto_dict[wav_file] = []

            wav_file_resolved = path.join(oto_path, wav_file)
            if not path.isfile(wav_file_resolved):
                print(f"Warning: Could not find wav file {wav_file_resolved}, skip this line.")
                continue
            
            with open_wave(wav_file_resolved, 'rb') as wav:
                wav_params = wav.getparams()
                wav_length = wav_params.nframes / wav_params.framerate * 1000

            alias, offset, consonant, cutoff, preutterance, overlap = oto_params.split(",")

            offset = float(offset)
            consonant = float(consonant)
            cutoff = float(cutoff)
            preutterance = float(preutterance)
            overlap = float(overlap)
            # Make all of the values absolute
            consonant = max(offset + consonant, 0)
            preutterance = max(offset + preutterance, 0)
            overlap = max(offset + overlap, 0)

            if cutoff > 0:
                cutoff = max(consonant + 0.1, wav_length - offset)
            else:
                cutoff = min(wav_length, offset + (-1 * cutoff))

            oto_info = OtoInfo()
            oto_info.wav_file = wav_file_resolved
            oto_info.alias = alias
            oto_info.offset = offset
            oto_info.consonant = consonant
            oto_info.cutoff = cutoff
            oto_info.preutterance = preutterance
            oto_info.overlap = overlap

            oto_dict[wav_file].append(oto_info)

    # Sort the oto list by preutterance
    for oto_list in oto_dict.values():
        oto_list.sort(key=lambda x: x.preutterance)

    return oto_dict

global hiragana_map
with open("hiragana.json", "r", encoding="utf-8") as f:
    hiragana_map = json.load(f)

    for item in hiragana_map:
        item["phoneme"] = item["phoneme"].split(" ")

def get_hiragana_info(hiragana: str) -> Optional[JPhonemeMapItem]:
    global hiragana_map
    
    for item in hiragana_map:
        if item["kana"] == hiragana:
            return item
        
    return None
    
def get_romaji_info(romaji: str) -> Optional[JPhonemeMapItem]:
    global hiragana_map
    
    for item in hiragana_map:
        if item["romaji"] == romaji:
            return item
        
    return None

def romaji_is_vowel(romaji: str) -> bool:
    return romaji in ["a", "i", "u", "e", "o", "n", "N"]

def xsampa_is_vowel(xsampa: str) -> bool:
    return xsampa in ["a", "i", "M", "e", "o", "N\\"]

def get_phoneme_list_from_filename(filename: str) -> list[JPhonemeMapItem]:
    if re.match(r"^[\_\-ぁ-ゔァ-・]+", filename):
        # Hiragana
        hiragana_list = re.findall(r"[ぁ-ゔァ-・][ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ]?", filename)
        return [get_hiragana_info(hiragana) for hiragana in hiragana_list]
    elif re.match(r"^([a-zA-Z0-9\_\-])+", filename):
        if "__" in filename: # Remove prompt phoneme
            filename = filename[filename.index("__") + 2:]

        filename = filename.replace("-", "_").strip("_")
        # Romaji
        romaji_list = re.findall(r"[a-zA-Z][a-zA-Z]?", filename)
        return [get_romaji_info(romaji) for romaji in romaji_list]
    
    return []

def escape_xsampa(xsampa: str) -> str:
    """Escapes xsampa to file name."""
    xsampa = xsampa.replace("Sil", "sil") # Sil is a special case
    xsampa = xsampa.replace("\\", "-").replace("/", "~").replace("?", "!").replace(":", ";").replace("<", "(").replace(">", ")")
    xsampa = re.sub(r"([A-Z])", lambda x : x.group(1).lower() + "#", xsampa)
    return xsampa

def unescape_xsampa(xsampa: str) -> str:
    """Unescapes xsampa from file name."""
    xsampa = re.sub(r"([a-z])#", lambda x : x.group(1).upper(), xsampa)
    xsampa = xsampa.replace("-", "\\").replace("~", "/").replace("!", "?").replace(";", ":").replace("(", "<").replace(")", ">")
    return xsampa

def get_oto_entry_phoneme_info(oto_entry: OtoInfo) -> OtoEntryPhonemeInfo:
    """Returns phoneme info from an OtoInfo object."""
    item_alias = oto_entry.alias

    ret = OtoEntryPhonemeInfo()

    if re.match(r"[0-9]+$", item_alias): # Alternate phoneme
        ret.is_alternative = True
        item_alias = re.sub(r"[0-9]+$", "", item_alias)

    if item_alias[0] == "-": # R-C-V?
        item_alias = item_alias[1:].strip()
        if re.match(r"^([ぁ-ゔァ-・]+)$", item_alias): # Hiragana R-C-V:
            hiragana = item_alias.replace(" ", "")

            phoneme_info = get_hiragana_info(hiragana)

            if phoneme_info is None:
                raise Exception(f"[Hiragana R-C-V] Could not find phoneme info for {hiragana}")

            if len(phoneme_info["phoneme"]) == 1: # R-C or R-V
                if xsampa_is_vowel(phoneme_info["phoneme"][0]):
                    ret.type = "rv"
                else:
                    ret.type = "rc"
            else:
                ret.type = "rcv"

            ret.phoneme_info_list = [phoneme_info]
            ret.phoneme_list = phoneme_info["phoneme"]
        else: # Romaji R-C-V
            romaji = item_alias.replace(" ", "")

            phoneme_info = get_romaji_info(romaji)

            if phoneme_info is None:
                return None

            if len(phoneme_info["phoneme"]) == 1: # R-C or R-V
                if xsampa_is_vowel(phoneme_info["phoneme"][0]):
                    ret.type = "rv"
                else:
                    ret.type = "rc"
            elif len(phoneme_info["phoneme"]) == 2:
                ret.type = "rcv"
            else:
                raise Exception(f"[Romaji R-C] Invalid phoneme info for {romaji}")
            
            ret.phoneme_info_list = [phoneme_info]
            ret.phoneme_list = phoneme_info["phoneme"]
    elif item_alias[-1] == "-": # V-R
        item_alias = item_alias[:-1].strip()
        if re.match(r"^([aiueonN])$", item_alias): # Romaji V-R
            romaji = item_alias.replace(" ", "")

            phoneme_info = get_romaji_info(romaji)

            if phoneme_info is None:
                raise Exception(f"[Romaji VR] Could not find phoneme info for {romaji}")

            if len(phoneme_info["phoneme"]) == 1:
                ret.type = "vr"

                ret.phoneme_info_list = [phoneme_info]
                ret.phoneme_list = phoneme_info["phoneme"]
            else:
                raise Exception(f"[Romaji VR] Invalid phoneme info for {romaji}")
        else:
            raise Exception(f"[Romaji VR] Invalid phoneme info for {item_alias}")
    elif re.match(r"^([aiueoN]) ([aiueoN]|[あいうえおんアイウエオン])$", item_alias): # V-V
        matches = re.match(r"^([aiueoN]) ([aiueoN]|[あいうえおんアイウエオン])$", item_alias)
        first_vowel = matches.group(1)
        second_vowel = matches.group(2)

        first_vowel_info = get_romaji_info(first_vowel)

        if re.match(r"[aiueoN]", second_vowel):
            second_vowel_info = get_romaji_info(second_vowel)
        else:
            second_vowel_info = get_hiragana_info(second_vowel)

        if first_vowel_info is None or second_vowel_info is None:
            raise Exception(f"[Romaji VV] Could not find phoneme info for {item_alias}")
        
        ret.type = "vv"
        ret.phoneme_info_list = [first_vowel_info, second_vowel_info]
        ret.phoneme_list = first_vowel_info["phoneme"] + second_vowel_info["phoneme"]
    elif re.match(r"^n ([あいうえおんアイウエオン])$", item_alias): # N-V
        matches = re.match(r"^n ([あいうえおんアイウエオン])$", item_alias)

        vowel = matches.group(1)

        n_info = get_hiragana_info("ん")
        vowel_info = get_hiragana_info(vowel)

        if n_info is None or vowel_info is None:
            raise Exception(f"[Romaji NV] Could not find phoneme info for {item_alias}")
        
        ret.type = "vv" # N-V is the same as V-V
        ret.phoneme_info_list = [n_info, vowel_info]
        ret.phoneme_list = n_info["phoneme"] + vowel_info["phoneme"]
    elif re.match(r"^([aiueoN]) ([a-zA-Z]+[aiueo]|[ぁ-ゔァ-・])$", item_alias): # V-C-V
        pass # TODO
    elif re.match(r"^([aiueonN]) ([a-zA-Z]+)$", item_alias) and not re.match(r"^n ([aiueo])$", item_alias): # V-C
        matches = re.match(r"^([aiueonN]) ([a-zA-Z]+)$", item_alias)
        vowel = matches.group(1)
        consonant = matches.group(2)

        vowel_info = get_romaji_info(vowel)
        consonant_info = get_romaji_info(consonant)

        if vowel_info is None or consonant_info is None:
            raise Exception(f"[Romaji VC] Could not find phoneme info for {item_alias}")
        
        vowel_phoneme = vowel_info["phoneme"][0]
        consonant_phoneme = consonant_info["phoneme"][0]
        
        if vowel_phoneme == "N\\":
            # N variants
            if consonant_phoneme in ["n", "d", "d'", "t", "t'", "4", "4'", "dz", "dZ", "ts", "tS"]:
                vowel_phoneme = "n"
            elif consonant_phoneme in ["m", "m'", "p", "p'", "b", "b'"]:
                vowel_phoneme = "m"
            elif consonant_phoneme in ["g", "k"]:
                vowel_phoneme = "N"
            elif consonant_phoneme == "J":
                vowel_phoneme = "J"
            elif consonant_phoneme in ["g'", "k'"]:
                vowel_phoneme = "N'"

        vowel_info = vowel_info.copy()
        vowel_info["phoneme"] = [vowel_phoneme]
        
        ret.type = "vc"
        ret.phoneme_info_list = [vowel_info, consonant_info]
        ret.phoneme_list = vowel_info["phoneme"] + consonant_info["phoneme"]
    elif re.match(r"^([a-zA-Z ]+ ?[aiueonN]|[ぁ-ゔァ-・]+)$", item_alias): # C-V
        if re.match(r"^[a-zA-Z ]+$", item_alias):
            romaji = item_alias.replace(" ", "")
            phoneme_info = get_romaji_info(romaji)
        else:
            hiragana = item_alias.replace(" ", "")
            phoneme_info = get_hiragana_info(hiragana)

        if phoneme_info is None:
            raise Exception(f"[Romaji CV] Could not find phoneme info for {item_alias}")
        
        ret.type = "cv"
        ret.phoneme_info_list = [phoneme_info]
        ret.phoneme_list = phoneme_info["phoneme"]
    else:
        raise Exception(f"[Unknown Type] Invalid phoneme info for {item_alias}")
    
    return ret

def get_vowel_variants(vowel: str):
    """Returns a list of vowel variants."""
    vowel_variants = [vowel]

    for variant_list in vowel_variant_list:
        if vowel in variant_list:
            vowel_variants += variant_list
    
    # Deduplicate
    unique_vowel_variants = []
    for variant in vowel_variants:
        if variant not in unique_vowel_variants:
            unique_vowel_variants.append(variant)

    return unique_vowel_variants

def get_consonant_variants(consonant: str):
    """Returns a list of consonant variants."""
    consonant_variants = [consonant]

    for variant_list in consonant_variant_list:
        if consonant in variant_list:
            consonant_variants += variant_list
    
    # Deduplicate
    unique_consonant_variants = []
    for variant in consonant_variants:
        if variant not in unique_consonant_variants:
            unique_consonant_variants.append(variant)

    return unique_consonant_variants