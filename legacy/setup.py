from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="gemini-client-api",
    version="0.1.0",
    author="Trần Đăng Khoa",
    author_email="trandangkhoa.automation@gmail.com",
    description="A Python client for interacting with Google's Gemini API using curl_cffi.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/TranDangKhoaTechnology/Gemini-Chat-API",
    packages=find_packages(where=".", include=["gemini_client", "gemini_client.*"]),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.7", # Based on f-strings, asyncio, pydantic v2 features
    install_requires=[
        "curl_cffi>=0.5.9",
        "pydantic>=2.0",
        "rich>=10.0",
        "requests>=2.20",
        "browser-cookie3>=0.20.1",
    ],
    keywords="gemini google ai api client curl_cffi async",
    project_urls={
        "Bug Reports": "https://github.com/TranDangKhoaTechnology/Gemini-Chat-API/issues",
        "Source": "https://github.com/TranDangKhoaTechnology/Gemini-Chat-API",
    },
)
