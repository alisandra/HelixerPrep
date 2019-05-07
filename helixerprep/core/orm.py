from geenuff import orm
from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint, CheckConstraint, String
from sqlalchemy.orm import relationship


class Mer(orm.Base):
    __tablename__ = "mer"

    id = Column(Integer, primary_key=True)
    coordinate_id = Column(Integer, ForeignKey('coordinate.id'), nullable=False)

    mer_sequence = Column(String, nullable=False)
    count = Column(Integer)
    length = Column(Integer)

    coordinate = relationship('orm.Coordinate')

    __table_args__ = (
        UniqueConstraint('mer_sequence', 'coordinate_id', name='unique_kmer_per_coord'),
        CheckConstraint('length(mer_sequence) > 0', name='check_string_gt_0'),
        CheckConstraint('count >= 0', name='check_count_gt_0'),
        CheckConstraint('length >= 1', name='check_length_gt_1'),
    )