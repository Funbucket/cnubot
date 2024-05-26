from airflow.decorators import dag, task
from airflow.models import Param
from common_task import save_json, scrap_menu
from settings import LIFE_SCIENCE_URL, START_KR_DATE


@task(task_id="scrap_life_science_menu")
def scrap_life_science_menu(url: str) -> str:
    return scrap_menu(url, place="life_science")


@task(task_id="save_life_science_menu")
def save_life_science_menu(data: str) -> None:
    save_json(
        data,
        f"./data/life_science_menu.json",
    )


@dag(
    dag_id="ETL_life_science_hall_menu",
    description="ETL pipeline for scraping and saving the second student hall menu data in JSON format.",
    params={
        "life_science_URL": Param(
            title="Second Student Hall URL",
            description="Provide the URL for the second student hall menu",
            default=LIFE_SCIENCE_URL,
            type="string",
        ),
    },
    start_date=START_KR_DATE,
    schedule_interval="0 0 * * 0",
    catchup=True,
)
def pipeline():
    scraped_data = scrap_life_science_menu("{{ params.life_science_URL }}")
    save_life_science_menu(scraped_data)


dag = pipeline()
