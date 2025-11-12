
  

# AndroidFileHost Scraper

Simple and powerful Python script to look for keywords and download files from AndroidFileHost by imitating their API calls. Supports downloading from multiple pages, mirror selection and sorting pages.

  

![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/codefl0w/AndroidFileHostScraper/total?style=flat-square&logo=github) ![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/codefl0w/AndroidFileHostScraper/.github%2Fworkflows%2Fbuild.yml?style=flat-square&label=Executable%20build%20workflow)

  

  
  

## Why?

  

AFH is slowly dying, which means a lot of ROMs, kernels and whatnot will be forever gone if we don't archive them elsewhere. This script makes everything a lot easier.

  

## Installation

Get the requirements: `pip install requests beautifulsoup4`

And run the script.

  

You can also check the [releases](https://github.com/codefl0w/AndroidFileHostScraper/releases) page to download precompiled executables for your platform if you don't want to install Python. Releases are created automatically using GitHub Actions and mostly untested, so please create an issue if you encounter a problem.

  

Lastly, you can install the PyPi distribution globally by running `pip install AndroidFileHostScraper`. You can then call it via either `AndroidFileHostScraper` or `afhscraper` in your terminal.

  

## Usage

### Interactive mode

Just run the tool, search for keywords, select your preferences and wait. The scraper will automatically go through the files and download them.

Downloads can be found within the root directory of the script.

### CLI Mode

AFHScraper V2.0.0 and later can take positional arguements and run like a CLI tool.

    options:
      -h, --help            show this help message and exit
      -s, --search SEARCH   Search terms (comma-separated)
      --sort {newest,popular}
                            Sort order (newest or popular)
      -n, --files FILES     Maximum files to download per search term
      -m, --mirror {usa,germany}
                            Preferred mirror location
      -t, --threads THREADS
                            Number of concurrent downloads (default: 1)
      -o, --output OUTPUT   Download directory
      -l, --log-level {DEBUG,INFO,WARNING,ERROR}
                            Logging level (default: INFO)


This can be used to automate downloads. It also lets the user to specify an output directory unlike the interactive mode.

For example, to download the first 20 most popular files each from "twrp" and "lineage" searches with 5 threads from a USA server with DEBUG level outputs:

    python AFHscraper.py -s "twrp,lineage" --sort popular -n 20 -t 5 -m usa -l DEBUG
And so on.

### Extras

Enjoy my work? Please consider a small donation!

<a href="https://buymeacoffee.com/fl0w" target="_blank" rel="noopener noreferrer">
  <img width="350" alt="yellow-button" src="https://github.com/user-attachments/assets/2e6d44c8-9640-4cb3-bcc8-989595d6b7e9"/>
</a>

