## Celery docs

- Install the dependencies
```bash
$ pip install -r requirements.txt
```

- Make sure you have a Redis Server running: `redis://localhost:6379`
  - `$ redis-cli` and type `ping` 
- In the base directory inside `tasks_scripts` folder you need to write your scripts file.
- Run the celery command from the CLI.

```bash
$ export DJANGO_SETTINGS_MODULE="core.settings"  
$ celery -A apps.tasks worker -l info -B
```
- Run the django server
```bash
$ python manage.py runserver
```
- You will see a new route `Tasks` in the sidebar.
- You can start and cancel any task from the UI.