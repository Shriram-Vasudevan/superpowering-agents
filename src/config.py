from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    unsplash_access_key: str = ""
    model_name: str = "claude-sonnet-4-6-20250627"
    max_references: int = 5
    max_screenshot_width: int = 1200

    # Paths (relative to project root)
    project_root: Path = Path(__file__).resolve().parent.parent
    reference_data_dir: Path = Path("")
    index_data_dir: Path = Path("")
    screenshots_dir: Path = Path("")

    model_config = {"env_file": ".env", "extra": "ignore"}

    def model_post_init(self, __context: object) -> None:
        if self.reference_data_dir == Path(""):
            self.reference_data_dir = self.project_root / "reference_data"
        if self.index_data_dir == Path(""):
            self.index_data_dir = self.project_root / "index_data"
        if self.screenshots_dir == Path(""):
            self.screenshots_dir = self.reference_data_dir / "screenshots"

    @property
    def embeddings_path(self) -> Path:
        return self.reference_data_dir / "all_embeddings.npy"

    @property
    def catalog_path(self) -> Path:
        return self.reference_data_dir / "style_catalog.json"

    @property
    def domain_to_row_path(self) -> Path:
        return self.index_data_dir / "domain_to_row.json"

    @property
    def catalog_index_path(self) -> Path:
        return self.index_data_dir / "catalog_index.json"

    @property
    def industry_profiles_path(self) -> Path:
        return self.index_data_dir / "industry_style_profiles.json"


settings = Settings()
