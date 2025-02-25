## OAuth

> Intro: What we offer

OAuth, or "Open Authorization", is an open standard for access delegation. It's a protocol that lets users pass authorization from one service to another without sharing their credentials. These services can be Google, Github, Microsoft, Linkedin, etcetera. Level up your user experience with **Rocket Django PRO's** seamless OAuth logins.


### Setting up OAuth for Rocket Django PRO

> How to use it 

Rocket Django PRO utilizes [django-allauth](https://docs.allauth.org/en/latest/installation/quickstart.html) library for OAuth implementation. The services that are integrated are defined in `core/settings.py` under the `SOCIALACCOUNT_PROVIDERS` setting.
```py
# core/settings.py
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        "APP": {
            "client_id": GOOGLE_CLIENT_ID,
            "secret": GOOGLE_SECRET_KEY,
        },
    },
    'github': {
        "APP": {
            "client_id": GITHUB_CLIENT_ID,
            "secret": GITHUB_SECRET_KEY,
        },
    },
}
```
More services can be integrated by extending this setting to accommodate more providers.


#### Getting Google Credentials

- Visit [Google developer console](https://console.cloud.google.com/). From the sidebar menu, navigate to `Credentials` under `APIs and services`.

![Google developer console](https://github.com/app-generator/dummy/assets/57325382/e63df707-d066-453e-a7d2-8ea5425ba85b)

- Create a new OAuth Client ID, copy the `Client ID` and `Client secret` and add them to your `.env` file, using the `GOOGLE_CLIENT_ID` and `GOOGLE_SECRET_KEY` keys respectively.

![Google developer console OAuth page](https://github.com/app-generator/dummy/assets/57325382/bbfaad26-2a4a-4876-bdc9-e23b1e88eaab)

- Add the following as the authorised redirects URIs:
    - http://127.0.0.1:8000/accounts/google/login/callback/
    - http://localhost:8000/accounts/google/login/callback/

    Depending on where the application is hosted, you will have to substitute `localhost:8000` and `127.0.0.1:8000` with the base URL of the hosted application.


#### Getting GitHub credentials

- Visit [Github](https://github.com/settings) settings page. From the sidebar click on `Developer settings`.

![Github settings page](https://github.com/app-generator/dummy/assets/57325382/abbea42b-c2d5-4981-ba41-dfc4920cbcc9)

- From the `Developer Settings`, go to `OAuth Apps` and Register a new application.

![Github register new OAuth application page](https://github.com/app-generator/dummy/assets/57325382/c92ba91d-d5da-4e48-854b-fd210f06e0ec)

- The Homepage URL is the same as the homepage URL used when creating the Google credentials. The `Authorization callback URL` should be http://127.0.0.1:8000/accounts/github/login/callback/.

- After registering the application, generate a new client secret. Copy the client ID and client secret and add them to the `.env` file with the keys `GITHUB_CLIENT_ID` and `GITHUB_SECRET_KEY` respectively.

![Github App OAuth page](https://github.com/app-generator/dummy/assets/57325382/1fd2387e-d884-4867-870f-5258dd0f77c3)

- The `.env` file in the root directory should contain the following credentials
```bash
GOOGLE_CLIENT_ID=
GOOGLE_SECRET_KEY=

GITHUB_CLIENT_ID=
GITHUB_SECRET_KEY=
```


### Working with the sign-in template
The sign-in template located in `templates/authentication/sign-in.html` implements the OAuth sign-in function.
```jinja
<!--templates/authentication/sign-in.html-->
{% load static socialaccount %}
{% get_providers as socialaccount_providers %}
...
<form action="{% provider_login_url 'google' %}" method="post">
    {% csrf_token %}
    <button type="submit" class="text-gray-900 bg-white hover:bg-gray-100 border border-gray-200 focus:ring-4 focus:outline-none focus:ring-gray-100 font-medium rounded-lg text-sm px-5 py-2.5 text-center inline-flex items-center dark:focus:ring-gray-600 dark:bg-gray-800 dark:border-gray-700 dark:text-white dark:hover:bg-gray-700 mr-2 ">
        <svg class="h-4 mr-1 -ml-1 w-7" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 18 19">
            <path fill-rule="evenodd" d="M8.842 18.083a8.8 8.8 0 0 1-8.65-8.948 8.841 8.841 0 0 1 8.8-8.652h.153a8.464 8.464 0 0 1 5.7 2.257l-2.193 2.038A5.27 5.27 0 0 0 9.09 3.4a5.882 5.882 0 0 0-.2 11.76h.124a5.091 5.091 0 0 0 5.248-4.057L14.3 11H9V8h8.34c.066.543.095 1.09.088 1.636-.086 5.053-3.463 8.449-8.4 8.449l-.186-.002Z" clip-rule="evenodd"/>
        </svg>
        Log in with Google
    </button>
</form>
<form action="{% provider_login_url 'github' %}" method="post">
    {% csrf_token %}
    <button type="submit" class="text-gray-900 bg-white hover:bg-gray-100 border border-gray-200 focus:ring-4 focus:outline-none focus:ring-gray-100 font-medium rounded-lg text-sm px-5 py-2.5 text-center inline-flex items-center dark:focus:ring-gray-600 dark:bg-gray-800 dark:border-gray-700 dark:text-white dark:hover:bg-gray-700 mr-2">
        <svg class="h-4 mr-1 -ml-1 w-7" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M10 .333A9.911 9.911 0 0 0 6.866 19.65c.5.092.678-.215.678-.477 0-.237-.01-1.017-.014-1.845-2.757.6-3.338-1.169-3.338-1.169a2.627 2.627 0 0 0-1.1-1.451c-.9-.615.07-.6.07-.6a2.084 2.084 0 0 1 1.518 1.021 2.11 2.11 0 0 0 2.884.823c.044-.503.268-.973.63-1.325-2.2-.25-4.516-1.1-4.516-4.9A3.832 3.832 0 0 1 4.7 7.068a3.56 3.56 0 0 1 .095-2.623s.832-.266 2.726 1.016a9.409 9.409 0 0 1 4.962 0c1.89-1.282 2.717-1.016 2.717-1.016.366.83.402 1.768.1 2.623a3.827 3.827 0 0 1 1.02 2.659c0 3.807-2.319 4.644-4.525 4.889a2.366 2.366 0 0 1 .673 1.834c0 1.326-.012 2.394-.012 2.72 0 .263.18.572.681.475A9.911 9.911 0 0 0 10 .333Z" clip-rule="evenodd"/>
        </svg>
        Log in with Github
    </button>
</form>
```

`<form action="{% provider_login_url 'google' %}" method="post">` and `<form action="{% provider_login_url 'github' %}" method="post">` are used to implement the specific OAuth service for a provider.

Visit http://127.0.0.1:8000/users/signin/ from your browser to explore the OAuth functionality of **Rocket Django PRO**.

![Rocket Django PRO signin page](https://github.com/app-generator/dummy/assets/57325382/8d96c33e-1c0b-4d19-8543-b84bc55e3338)


## Conclusion
Say goodbye to tedious sign-up forms and hello to frictionless logins! **Rocket Django PRO's** powerful OAuth integration empowers you to boost user engagement and security with the magic of single sign-on.


## ✅ Resources
- 👉 [Django-Allauth](https://docs.allauth.org/en/latest/introduction/index.html) Documentation
- 👉 [Rocket Django](https://docs.appseed.us/products/rocket/django/) product offering
- 👉 Join the [Community](https://discord.com/invite/fZC6hup) and chat with the team behind **Rocket Django**