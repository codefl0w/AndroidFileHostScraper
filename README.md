
# AndroidFileHost Scraper
Simple and powerful Python script to look for keywords and download files from AndroidFileHost by imitating their API calls. Supports downloading from multiple pages, mirror selection and sorting pages.

![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/codefl0w/AndroidFileHostScraper/total?style=flat-square&logo=github) ![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/codefl0w/AndroidFileHostScraper/.github%2Fworkflows%2Fbuild.yml?style=flat-square&label=Executable%20build%20workflow)

 


## Why?

AFH is slowly dying, which means a lot of ROMs, kernels and whatnot will be forever gone if we don't archive them elsewhere. This script makes everything a lot easier.

## Installation
Get the requirements: `pip install requests beautifulsoup4` 
And run the script. 

You can also check the [releases](https://github.com/codefl0w/AndroidFileHostScraper/releases) page to download precompiled executables for your platform if you don't want to install Python. Releases are created automatically using GitHub Actions and mostly untested, so please create an issue if you encounter a problem.

## Usage
Just run the script, search for keywords, select how the files should be listed, choose the amount of files to download, select your primary server and hit enter. The scraper will automatically go through the files and download them.

Downloads can be found within the root directory of the script.



