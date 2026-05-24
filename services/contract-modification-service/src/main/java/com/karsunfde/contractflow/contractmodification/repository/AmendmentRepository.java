package com.karsunfde.contractflow.contractmodification.repository;

import com.karsunfde.contractflow.contractmodification.model.Amendment;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface AmendmentRepository extends MongoRepository<Amendment, String> {

    List<Amendment> findByContractModificationIdOrderByNumberAsc(String contractModificationId);

    /** ⚠ Item 10 — declared but unused. */
    List<Amendment> findByAgencyId(String agencyId);
}
