from airflow.decorators import dag, task
from airflow.models import Param
from common_task import save_json, scrap_menu
from settings import SANGROK_URL, START_KR_DATE


@task(task_id="scrap_sangrok_menu")
def scrap_sangrok_menu(url: str) -> str:
    return scrap_menu(url, place="sangrok")


@task(task_id="save_sangrok_menu")
def save_sangrok_menu(data: str) -> None:
    save_json(data, f"./data/sangrok_menu.json")


@dag(
    dag_id="ETL_sangrok_hall_menu",
    description="ETL pipeline for scraping and saving the second student hall menu data in JSON format.",
    params={
        "sangrok_URL": Param(
            title="Second Student Hall URL",
            description="Provide the URL for the second student hall menu",
            default=SANGROK_URL,
            type="string",
        ),
    },
    start_date=START_KR_DATE,
    schedule_interval="0 0 * * 0",
    catchup=True,
)
def pipeline():
    scraped_data = scrap_sangrok_menu("{{ params.sangrok_URL }}")
    save_sangrok_menu(scraped_data)


dag = pipeline()
