package com.karsunfde.contractflow.contractmodification.repository;

import com.karsunfde.contractflow.contractmodification.model.Qna;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface QnaRepository extends MongoRepository<Qna, String> {

    List<Qna> findByContractModificationId(String contractModificationId);

    /** ⚠ Item 10 — declared but unused. */
    List<Qna> findByAgencyId(String agencyId);
}
