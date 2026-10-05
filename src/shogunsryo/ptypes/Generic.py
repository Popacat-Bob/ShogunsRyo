from dataclasses import dataclass 

type RGB = tuple[int, int, int]

@dataclass(frozen=True)
class Dimensions:
    width: int 
    height: int

@dataclass(frozen=True)
class Coords:
    x: int 
    y: int

@dataclass(frozen=True)
class Bbox:
    TopLeft: Coords
    BotRight: Coords
    
    @property
    def width(self):
        return self.BotRight.x - self.TopLeft.x
    
    @property
    def height(self):
        return self.BotRight.y - self.TopLeft.y
    
    @property
    def mid(self) -> Coords:
        return Coords(
                self.TopLeft.x + self.width // 2,
                self.TopLeft.y + self.height // 2
                )
