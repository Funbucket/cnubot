from airflow.decorators import dag, task
from airflow.models import Param
from common_task import save_json, scrap_menu
from settings import HALL_2_URL, START_KR_DATE


@task(task_id="scrap_hall_2_menu")
def scrap_hall_2_menu(url: str) -> str:
    return scrap_menu(url, "hall_2")


@task(task_id="save_hall_2_menu")
def save_hall_2_menu(data: str) -> None:
    save_json(data, f"./data/hall_2_menu.json")


@dag(
    dag_id="ETL_second_student_hall_menu",
    description="ETL pipeline for scraping and saving the second student hall menu data in JSON format.",
    params={
        "HALL_2_URL": Param(
            title="Second Student Hall URL",
            description="Provide the URL for the second student hall menu",
            default=HALL_2_URL,
            type="string",
        ),
    },
    start_date=START_KR_DATE,
    schedule_interval="0 0 * * 0",
    catchup=True,
)
def pipeline():
    scraped_data = scrap_hall_2_menu("{{ params.HALL_2_URL }}")
    save_hall_2_menu(scraped_data)


dag = pipeline()
